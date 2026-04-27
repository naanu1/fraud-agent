"""
3 agents: researcher -> analyst -> evaluator
- emit() callback for real-time SSE streaming (noop when running from CLI)
- Parallel tool calls (Tavily + Serper + Sanctions simultaneously)
- 3-retry with 30s gap on LLM failures
- Agent 3 -> Agent 1 query refinement feedback loop
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from config import (GEMINI_API_KEY, GROQ_API_KEY,
                    PRIMARY_MODEL, EVALUATOR_MODEL, FALLBACK_MODEL,
                    STAGNATION_LIMIT, MIN_CONFIDENCE)
from state import State, Entity, Fact, Flag, is_same_entity, is_duplicate_queue_entry
from tools import web_search, targeted_search, sanctions_check

log = logging.getLogger("agent")
SEP = "=" * 55
_NOOP = lambda **kw: None  # default no-op emit for CLI path

def _llm(model: str, max_tokens: int = 4096):
    if not model:
        model = PRIMARY_MODEL
    primary = ChatGoogleGenerativeAI(
        model=model, google_api_key=GEMINI_API_KEY,
        temperature=0.1, max_output_tokens=max_tokens,
    )
    if GROQ_API_KEY:
        fallback = ChatGroq(model=FALLBACK_MODEL, groq_api_key=GROQ_API_KEY,
                            temperature=0.1, max_tokens=max_tokens)
        return primary.with_fallbacks([fallback])
    return primary


def _invoke_with_retry(chain, vars: dict, retries: int = 3, gap: int = 5):
    for attempt in range(retries):
        try:
            return chain.invoke(vars)
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = gap * (2 ** attempt)  # 5s, 10s
            log.warning(f"LLM attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
            time.sleep(wait)


# ---------------------------------------------------------------------------
# Structured output schemas
# ---------------------------------------------------------------------------
class QueryPlan(BaseModel):
    tavily_queries:  list[str] = Field(default_factory=list,
        description="1-3 broad web search queries")
    serper_queries:  list[str] = Field(default_factory=list,
        description="0-2 precise site: queries e.g. '\"Name\" site:sec.gov'")
    sanctions_names: list[str] = Field(default_factory=list,
        description="Names to run through sanctions API")


class ExtractionResult(BaseModel):
    facts:    list[Fact]   = Field(default_factory=list,
        description="Verified facts. Every fact MUST have a non-empty quote field.")
    entities: list[Entity] = Field(default_factory=list,
        description="New entities to investigate (people, companies, LLCs)")


class RiskResult(BaseModel):
    flags:            list[Flag] = Field(default_factory=list)
    suggested_queries: list[str] = Field(default_factory=list,
        description="Specific search queries Agent 1 should run next to fill coverage gaps")


# ---------------------------------------------------------------------------
# Parallel search runner
# ---------------------------------------------------------------------------
def _run_parallel_searches(plan: QueryPlan, state: State, emit: Callable, iteration: int = 0) -> list[str]:
    tasks = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for q in plan.tavily_queries[:3]:
            q = q.strip()
            if q and q not in state.done_queries:
                state.done_queries.append(q)
                tasks.append(("tavily", q, pool.submit(web_search, q)))
        for q in plan.serper_queries[:2]:
            q = q.strip()
            if q and q not in state.done_queries:
                state.done_queries.append(q)
                tasks.append(("serper", q, pool.submit(targeted_search, q)))
        for name in plan.sanctions_names[:2]:
            name = name.strip()
            if name:
                tasks.append(("sanctions", name, pool.submit(sanctions_check, name)))

        raw_parts = []
        for tool, query, future in tasks:
            try:
                text = future.result(timeout=25)
                status = "ok" if text and len(text) > 50 else "empty"
                log.info(f"  [{tool.upper()}] {query[:60]} -> {len(text)} chars ({status})")
                emit(event="query_executed", tool=tool, query=query,
                     iteration=iteration, result_chars=len(text), status=status)
                if status == "ok":
                    raw_parts.append(f"=== {tool.upper()}: {query} ===\n{text}")
            except Exception as e:
                log.warning(f"  [{tool.upper()}] {query[:50]} FAILED: {e}")
                emit(event="query_executed", tool=tool, query=query,
                     iteration=iteration, result_chars=0, status="empty")
    return raw_parts


# ---------------------------------------------------------------------------
# AGENT 1 — RESEARCHER
# ---------------------------------------------------------------------------
def researcher(state: State, emit: Callable = _NOOP) -> State:
    state.iteration += 1
    model = state.researcher_model or PRIMARY_MODEL
    log.info(f"\n{SEP}\nITERATION {state.iteration} — AGENT 1: RESEARCHER\n{SEP}")
    emit(event="iteration_start", iteration=state.iteration, max_iterations=state.max_iterations)
    emit(event="agent_start", agent="researcher", iteration=state.iteration, model=model)

    unsearched = [e for e in state.queue if not e.searched]
    if not unsearched:
        log.info("Queue empty — concluding.")
        emit(event="agent_log", agent="researcher", message="Queue empty — concluding.")
        state.concluded = True
        emit(event="agent_end", agent="researcher", iteration=state.iteration)
        return state

    entity = max(unsearched, key=lambda e: e.priority)
    log.info(f"Entity: {entity.name} | type={entity.type} | priority={entity.priority}")
    emit(event="agent_log", agent="researcher",
         message=f"Investigating: {entity.name} ({entity.type}, priority={entity.priority})")

    is_first = (state.iteration == 1)

    if is_first:
        system = (
            "You are an investigative researcher. Plan a BROAD SWEEP for a new person.\n"
            "Generate exactly 3 tavily_queries and 2 serper_queries:\n"
            "  tavily_queries:\n"
            "      1. Personal life ONLY — name + age, hometown, personal real estate, side businesses, local investments.\n"
            "         DO NOT include the company/organization name in this query — it over-filters results.\n"
            "      2. Legal/regulatory — name + SEC charges, FINRA enforcement, fraud, lawsuits, personal draws, client losses.\n"
            "      3. Family and associates — name + family members fraud history, associates, crypto schemes, unregistered securities.\n"
            "  serper_queries:\n"
            "      1. site:sec.gov search for official charges\n"
            "      2. site:finra.org search for license/registration records\n"
            "  sanctions_names: [the person's full name]\n"
            "Always put the person's name in double quotes in every query.\n"
            "Keep queries short and specific — 5-8 words max."
        )
        human = "Investigate: {target}\nContext: {ctx}\nSuggested focus: {suggested}"
        invoke_vars = {"target": state.target, "ctx": state.context,
                       "suggested": ", ".join(state.suggested_queries) or "none"}
    else:
        system = (
            "You are an investigative researcher. Plan SURGICAL searches for ONE entity.\n"
            "Rules by entity type:\n"
            "  PERSON (legal context): 1 tavily (news/assets/fraud history) + 2 serper (site:sec.gov, site:courtlistener.com) + sanctions\n"
            "  PERSON (family member): MUST generate 2 tavily queries:\n"
            "      - Query 1: name + fraud, elder abuse, suspension, discipline, historical cases (go back decades)\n"
            "      - Query 2: name + current location, assets, businesses\n"
            "      Plus 1 serper (site:sec.gov) + sanctions\n"
            "  ORGANIZATION: 1 tavily + 2 serper (site:sec.gov, site:opencorporates.com)\n"
            "  Default PERSON: 2 tavily (news + assets) + 1 serper (site:finra.org) + sanctions\n"
            "Always put entity name in double quotes in queries.\n"
            "Incorporate any suggested focus areas into your queries."
        )
        human = (
            "Primary target: {target}\n"
            "Entity to investigate: \"{name}\" (type={etype})\n"
            "Context: {ctx}\n"
            "Suggested focus areas: {suggested}\n"
            "Already searched (skip): {done}"
        )
        invoke_vars = {
            "target": state.target, "name": entity.name, "etype": entity.type,
            "ctx": entity.context, "suggested": ", ".join(state.suggested_queries) or "none",
            "done": str(state.done_queries[-10:]),
        }

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    chain = _llm(model).with_structured_output(QueryPlan)

    try:
        prompt_str = str(prompt.format_messages(**invoke_vars))
        emit(event="llm_input", agent="researcher", iteration=state.iteration,
             prompt_preview=prompt_str[:500], full_prompt=prompt_str)
        plan: QueryPlan = _invoke_with_retry(prompt | chain, invoke_vars)
        emit(event="llm_output", agent="researcher", iteration=state.iteration,
             full_output=plan.model_dump_json())
        log.info(f"Query plan: tavily={plan.tavily_queries} serper={plan.serper_queries}")
    except Exception as e:
        log.warning(f"LLM query planning failed after retries: {e}")
        emit(event="agent_log", agent="researcher", message=f"Query planning failed: {e}. Using fallback.")
        if is_first:
            plan = QueryPlan(
                tavily_queries=[
                    f'"{state.target}" biography background business ventures',
                    f'"{state.target}" SEC fraud charges lawsuit enforcement',
                    f'"{state.target}" family associates crypto scheme',
                ],
                serper_queries=[f'"{state.target}" site:sec.gov', f'"{state.target}" site:finra.org'],
                sanctions_names=[state.target],
            )
        else:
            plan = QueryPlan(
                tavily_queries=[f'"{entity.name}" {state.target} fraud history'],
                serper_queries=[f'"{entity.name}" site:sec.gov'],
                sanctions_names=[entity.name] if entity.type == "PERSON" else [],
            )

    emit(event="agent_log", agent="researcher",
         message=f"Running {len(plan.tavily_queries)} Tavily + {len(plan.serper_queries)} Serper + {len(plan.sanctions_names)} sanctions queries in parallel")

    raw_parts = _run_parallel_searches(plan, state, emit, iteration=state.iteration)
    state.raw_text = "\n\n".join(raw_parts) if raw_parts else ""
    log.info(f"Collected {len(raw_parts)} blocks | {len(state.raw_text)} total chars")
    emit(event="agent_log", agent="researcher",
         message=f"Collected {len(raw_parts)} result blocks ({len(state.raw_text)} chars)")

    # Mark entity as searched — use is_duplicate_queue_entry to handle name variants
    for e in state.queue:
        if is_duplicate_queue_entry(entity.name, [e.name]):
            e.searched = True
    if not is_duplicate_queue_entry(entity.name, state.searched):
        state.searched.append(entity.name)

    emit(event="agent_end", agent="researcher", iteration=state.iteration)
    return state


# ---------------------------------------------------------------------------
# AGENT 2 — ANALYST
# ---------------------------------------------------------------------------
def analyst(state: State, emit: Callable = _NOOP) -> State:
    model = state.analyst_model or PRIMARY_MODEL
    log.info(f"\n{SEP}\nITERATION {state.iteration} — AGENT 2: ANALYST\n{SEP}")
    emit(event="agent_start", agent="analyst", iteration=state.iteration, model=model)

    raw = state.raw_text
    if not raw or not raw.strip():
        log.warning("raw_text is EMPTY — no data this iteration")
        emit(event="agent_log", agent="analyst", message="No data collected this iteration.")
        state.stagnation += 1
        emit(event="agent_end", agent="analyst", iteration=state.iteration)
        return state

    log.info(f"Analyzing {len(raw)} chars")
    emit(event="agent_log", agent="analyst", message=f"Analyzing {len(raw)} chars of research data...")
    raw = raw[:24_000]

    existing_summary = [f"{f.subject} | {f.relation} | {f.object}" for f in state.facts[:25]]

    system = """You are a forensic intelligence analyst extracting facts from source text.

DISAMBIGUATION GATE — CRITICAL:
Search engines frequently return results for different people or companies sharing the same name. You MUST verify identity before accepting any fact.

Target identity anchors:
  Name: {target}
  Known context: {context}

Disambiguation rules (apply to every source):
1. CHECK IDENTITY MARKERS: Compare the source's description of the person/company against the known context above (role, industry, location, time period). If they clearly conflict, REJECT the fact.
2. COMMON NAME RULE: If the name is common and the source describes a radically different life (deceased vs. active, different profession, different era), assign confidence = 0.35 — do not accept as fact about the target.
3. CORPORATE SUFFIX RULE: Legal entity suffixes matter (LLC vs Ltd vs Limited vs Corp vs Inc). A company in a different jurisdiction with a similar name is a separate legal entity UNLESS there is direct evidence linking it to the target (same directors, shared address, common ownership). Do NOT merge them.
4. INTERNATIONAL EXCEPTION: Do NOT reject facts simply because they involve a different country. Fraud frequently crosses borders via offshore accounts, shell companies, or foreign operations. Accept international facts IF they logically connect to the target (same person/company is mentioned as owner, director, or participant).
5. DOUBT RULE: When you cannot confirm the source is about the correct entity, set confidence = 0.35 (below the 0.60 acceptance threshold). It is better to miss an uncertain fact than to inject a wrong one.

CONFIDENCE SCORING:
  sec.gov / finra.org / justice.gov / court docs  -> 0.95
  Reuters / AP / Bloomberg / WSJ / NYT            -> 0.85
  Local/industry news                             -> 0.70
  OpenSanctions / OFAC                            -> 0.99
  Unverified / blog / obituary / ambiguous source -> 0.35

EXTRACTION RULES:
1. Extract EVERY concrete fact about the CORRECT target entity (only after passing the disambiguation gate above).
2. `quote` = exact verbatim sentence from source. REQUIRED on every fact.
3. `source_url` = the URL shown in the [SOURCE: ...] tag.
4. For entities: priority 9=legal/financial associate, 7=family member, 5=business contact.
5. Do NOT duplicate existing facts.
6. ALWAYS extract: age, founding year, dollar amounts, dates, locations, CRD/FINRA/SEC numbers.
7. ALWAYS extract: AUM (assets under management) amounts, number of clients/investors.
8. ALWAYS extract: personal draws, withdrawals, misappropriated funds with exact dollar amounts.
9. ALWAYS extract: specific financial products sold or pitched.
10. ALWAYS extract: asset purchases (real estate, vehicles, businesses) with amounts and dates.
11. ALWAYS extract: business ownership, LLC registrations, shell company structures.
12. ALWAYS extract: crypto or unregistered securities schemes with specific details.
13. ALWAYS extract: family member fraud history with dates, victims, amounts — even decades prior.
14. ALWAYS extract: suspensions, bans, license revocations with exact dates and durations.
15. ALWAYS extract: locations/addresses of target and associates.
16. ALWAYS extract: plea deals, settlements, restitution orders with exact amounts.
17. ALWAYS extract: continued operation after license revocation or suspension."""

    human = "Primary target: {target}\n\nExisting facts (no duplicates):\n{existing}\n\nSOURCE TEXT:\n{raw}"
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    chain = _llm(model, max_tokens=6000).with_structured_output(ExtractionResult)

    try:
        prompt_str = f"[target={state.target}] [context={state.context}] [existing={len(existing_summary)} facts] [raw={len(raw)} chars]"
        emit(event="llm_input", agent="analyst", iteration=state.iteration,
             prompt_preview=prompt_str, full_prompt=raw[:2000])
        result: ExtractionResult = _invoke_with_retry(prompt | chain, {
            "target": state.target,
            "context": state.context or "unknown",
            "existing": "\n".join(existing_summary) or "None yet.",
            "raw": raw,
        })
        emit(event="llm_output", agent="analyst", iteration=state.iteration,
             full_output=f"{len(result.facts)} facts, {len(result.entities)} entities extracted")
        log.info(f"LLM returned {len(result.facts)} facts, {len(result.entities)} entities")
    except Exception as e:
        log.warning(f"Analyst LLM failed: {e}")
        emit(event="agent_log", agent="analyst", message=f"Extraction failed: {e}")
        state.stagnation += 1
        state.raw_text = ""
        emit(event="agent_end", agent="analyst", iteration=state.iteration)
        return state

    new_facts = 0
    for f in result.facts:
        if not f.quote or len(f.quote.strip()) < 8:
            continue
        # Entity-resolved dedup: treat facts with same relation and same-entity subject/object as duplicates
        if any(
            is_same_entity(ef.subject, f.subject)
            and ef.relation.lower() == f.relation.lower()
            and is_same_entity(ef.object, f.object)
            for ef in state.facts
        ):
            continue
        state.facts.append(f)
        new_facts += 1
        log.info(f"FACT [{f.confidence:.2f}] {f.subject} -> {f.relation} -> {f.object}")
        emit(event="fact_found", iteration=state.iteration,
             subject=f.subject, relation=f.relation, object=f.object,
             confidence=f.confidence, source_url=f.source_url, quote=f.quote[:300])

    # Queue dedup: use conservative check — only block true duplicates, not family members
    # is_duplicate_queue_entry allows "Hansueli Overturf" even if "Hans Overturf" is known
    known_names = state.searched + [e.name for e in state.queue]
    new_ents = 0
    for e in result.entities:
        if not e.name:
            continue
        if is_duplicate_queue_entry(e.name, known_names):
            log.info(f"ENTITY SKIP (duplicate): {e.name}")
            continue
        state.queue.append(e)
        known_names.append(e.name)
        new_ents += 1
        log.info(f"ENTITY [{e.priority}] {e.name} ({e.type})")
        emit(event="entity_found", iteration=state.iteration,
             name=e.name, type=e.type, priority=e.priority, context=e.context)

    state.stagnation = 0 if (new_facts > 0 or new_ents > 0) else state.stagnation + 1
    log.info(f"SUMMARY: +{new_facts} facts | +{new_ents} entities | stagnation={state.stagnation}")
    emit(event="agent_log", agent="analyst",
         message=f"+{new_facts} facts, +{new_ents} new entities found. Stagnation: {state.stagnation}")

    state.raw_text = ""
    emit(event="agent_end", agent="analyst", iteration=state.iteration)
    return state


# ---------------------------------------------------------------------------
# AGENT 3 — EVALUATOR
# ---------------------------------------------------------------------------
def evaluator(state: State, emit: Callable = _NOOP) -> State:
    model = state.evaluator_model or EVALUATOR_MODEL
    log.info(f"\n{SEP}\nITERATION {state.iteration} — AGENT 3: EVALUATOR\n{SEP}")
    emit(event="agent_start", agent="evaluator", iteration=state.iteration, model=model)
    emit(event="agent_log", agent="evaluator",
         message=f"Assessing risk from {len(state.facts)} facts, {len(state.flags)} existing flags")

    qualified = [f for f in state.facts if f.confidence >= MIN_CONFIDENCE and f.quote]

    # Semantic flag groups — categories within the same group are treated as duplicates
    _FLAG_GROUPS = [
        {"SEC Enforcement Action", "Regulatory Violation", "Fiduciary Breach", "Misrepresentation"},
        {"Financial Fraud", "Asset Concealment"},
        {"Suspended/Revoked License", "Operating After Suspension"},
        {"Undisclosed Relationship", "Shell Company Structure"},
        {"Crypto/Unregistered Securities"},
        {"Legal Proceeding"},
        {"Sanctions Match"},
        {"Family Fraud History"},
    ]

    if qualified:
        existing_cats = {fl.category for fl in state.flags}

        def _cat_already_flagged(cat: str) -> bool:
            cat_l = cat.lower()
            # Exact match
            if any(ec.lower() == cat_l for ec in existing_cats):
                return True
            # Same semantic group — if any existing flag is in the same group, skip
            for group in _FLAG_GROUPS:
                if cat in group and any(ec in group for ec in existing_cats):
                    return True
            # Token overlap fallback (≥2 meaningful shared words)
            cat_tokens = {t for t in cat_l.split() if len(t) >= 4}
            for ec in existing_cats:
                ec_tokens = {t for t in ec.lower().split() if len(t) >= 4}
                if len(cat_tokens & ec_tokens) >= 2:
                    return True
            return False

        # Cap facts sent to evaluator to avoid LLM timeout (max 30 facts, quote capped at 120 chars)
        eval_facts = qualified[:30]
        facts_text = "\n".join(
            f"  [{f.confidence:.2f}] {f.subject} | {f.relation} | {f.object}\n"
            f"    src={f.source_url}\n    quote: {f.quote[:120]}"
            for f in eval_facts
        )
        facts_text = facts_text[:6000]  # hard cap to prevent LLM overload
        system = (
            "You are a forensic risk analyst. Flag the most significant risks from verified facts.\n\n"
            "SEVERITY: CRITICAL=active enforcement/charges | HIGH=confirmed violations | "
            "MEDIUM=pending/suspicious | LOW=historical\n\n"
            "CATEGORIES (use exactly one per flag — choose the most specific):\n"
            "  SEC Enforcement Action | Financial Fraud | Legal Proceeding | Sanctions Match |\n"
            "  Undisclosed Relationship | Shell Company Structure | Suspended/Revoked License |\n"
            "  Operating After Suspension | Crypto/Unregistered Securities | Family Fraud History |\n"
            "  Regulatory Violation | Misrepresentation | Asset Concealment | Fiduciary Breach\n\n"
            "IMPORTANT: Generate MAX 5 flags total. Do not create redundant flags for the same underlying event.\n"
            "  - SEC charge + fiduciary breach + misrepresentation from the SAME lawsuit = 1 flag (SEC Enforcement Action)\n"
            "  - Only split into separate flags if the events are genuinely distinct.\n"
            "Skip already-flagged categories: {existing}.\n"
            "Every flag needs at least one source URL.\n\n"
            "Also suggest 1-3 specific search queries to fill gaps in the investigation. "
            "Put these in suggested_queries."
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", system), ("human", "Facts:\n{facts}")
        ])
        chain = _llm(model, max_tokens=2048).with_structured_output(RiskResult)

        try:
            emit(event="llm_input", agent="evaluator", iteration=state.iteration,
                 prompt_preview=f"Evaluating {len(qualified)} qualified facts",
                 full_prompt=facts_text[:3000])
            result: RiskResult = _invoke_with_retry(prompt | chain, {
                "existing": ", ".join(existing_cats) or "none",
                "facts": facts_text,
            })
            emit(event="llm_output", agent="evaluator", iteration=state.iteration,
                 full_output=f"{len(result.flags)} flags, {len(result.suggested_queries)} suggested queries")

            for fl in result.flags:
                if not _cat_already_flagged(fl.category):
                    state.flags.append(fl)
                    existing_cats.add(fl.category)
                    log.info(f"FLAG [{fl.severity}] {fl.category}: {fl.description[:100]}")
                    emit(event="flag_found", iteration=state.iteration,
                         severity=fl.severity, category=fl.category,
                         description=fl.description, sources=fl.sources)

            if result.suggested_queries:
                state.suggested_queries = result.suggested_queries[:3]
                emit(event="next_queries", iteration=state.iteration,
                     suggested_queries=result.suggested_queries)
                log.info(f"Suggested next queries: {result.suggested_queries}")
        except Exception as e:
            log.warning(f"Evaluator LLM failed: {e}")
            emit(event="agent_log", agent="evaluator", message=f"Risk assessment failed: {e}")
    else:
        emit(event="agent_log", agent="evaluator", message="No qualified facts yet — skipping risk assessment.")

    # Routing — log full queue state for transparency
    unsearched = [e for e in state.queue if not e.searched]
    high_pri   = [e for e in unsearched if e.priority >= 7]
    log.info(f"Queue state: total={len(state.queue)}, unsearched={len(unsearched)}, "
             f"high_pri={len(high_pri)}, stagnation={state.stagnation}")
    for e in state.queue:
        log.info(f"  {'[DONE]' if e.searched else '[TODO]'} {e.name} (priority={e.priority})")

    if state.iteration >= state.max_iterations:
        emit(event="agent_log", agent="evaluator", message="Stopping: max iterations reached.")
        state.concluded = True
    elif not unsearched:
        emit(event="agent_log", agent="evaluator", message="Stopping: all entities investigated.")
        state.concluded = True
    elif not high_pri and state.stagnation >= STAGNATION_LIMIT:
        emit(event="agent_log", agent="evaluator",
             message=f"Stopping: stagnation={state.stagnation}, no high-priority entities left.")
        state.concluded = True
    else:
        next_entity = max(unsearched, key=lambda e: e.priority)
        emit(event="agent_log", agent="evaluator",
             message=f"Continuing: {len(unsearched)} entities in queue. Next: {next_entity.name} (priority={next_entity.priority})")

    emit(event="agent_end", agent="evaluator", iteration=state.iteration)
    return state
