"""
Usage:
  python main.py --name "Timothy Overturf" --context "CEO of Sisu Capital"
  python main.py --name "Sam Bankman-Fried" --context "Founder of FTX"
"""
import argparse
import webbrowser
from pathlib import Path

from utils import setup_logging
setup_logging()

import logging
log = logging.getLogger("main")

from state import State, Entity
from config import PRIMARY_MODEL, MAX_ITERATIONS
from graph import run
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from config import GEMINI_API_KEY, GROQ_API_KEY, FALLBACK_MODEL
from langchain_groq import ChatGroq


class AliasResult(BaseModel):
    aliases: list[str]


def get_aliases(name: str) -> list[str]:
    try:
        llm = ChatGoogleGenerativeAI(
            model=PRIMARY_MODEL, google_api_key=GEMINI_API_KEY,
            temperature=0, max_output_tokens=256,
        )
        if GROQ_API_KEY:
            llm = llm.with_fallbacks([ChatGroq(
                model=FALLBACK_MODEL, groq_api_key=GROQ_API_KEY,
                temperature=0, max_tokens=256,
            )])
        prompt = ChatPromptTemplate.from_messages([
            ("human", (
                "List all name variants for: {name}\n"
                "Include: short forms, formal, initials, known aliases.\n"
                "Return as JSON matching AliasResult schema (field 'aliases': list of strings)."
            )),
        ])
        result: AliasResult = (prompt | llm.with_structured_output(AliasResult)).invoke({"name": name})
        return list(dict.fromkeys([name] + result.aliases))
    except Exception as e:
        log.warning(f"Alias resolution failed: {e}")
        parts = name.split()
        variants = [name]
        if len(parts) >= 2:
            variants.append(parts[0])
            variants.append(parts[0][0] + ". " + " ".join(parts[1:]))
        return variants


def extract_org(context: str, name: str) -> str:
    """Pull org name from context string using simple heuristics."""
    if not context:
        return ""
    for prep in ["of ", "at ", "for "]:
        if prep in context.lower():
            idx = context.lower().index(prep)
            org = context[idx + len(prep):].strip().rstrip(".,")
            if org and org.lower() != name.lower() and len(org) < 80:
                return org
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name",       required=True)
    parser.add_argument("--context",    default="")
    parser.add_argument("--iterations", type=int, default=MAX_ITERATIONS)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  DEEP RESEARCH AGENT")
    print(f"  Target  : {args.name}")
    print(f"  Context : {args.context or '(none)'}")
    print(f"{'='*55}\n")

    log.info(f"Resolving aliases for: {args.name}")
    aliases = get_aliases(args.name)
    log.info(f"Aliases: {aliases}")

    state = State(
        target=args.name,
        context=args.context,
        aliases=aliases,
        max_iterations=args.iterations,
    )

    # Seed queue: primary target (priority 10) + their org (priority 9)
    state.queue.append(Entity(
        name=args.name, type="PERSON", priority=10,
        context=f"Primary target. {args.context}",
    ))
    org = extract_org(args.context, args.name)
    if org:
        state.queue.append(Entity(
            name=org, type="ORGANIZATION", priority=9,
            context=f"Organization linked to {args.name}.",
        ))
        log.info(f"Seeded org: {org}")

    final = run(state)

    sevs = [f.severity for f in final.flags]
    risk = next((v for v in ["CRITICAL","HIGH","MEDIUM","LOW"] if v in sevs), "CLEAN")

    print(f"\n{'='*55}")
    print(f"  DONE  |  Risk: {risk}  |  Flags: {len(final.flags)}  |  Facts: {len(final.facts)}")
    print(f"  Iterations: {final.iteration}  |  Entities found: {len(final.queue)}")
    print(f"{'='*55}")

    if final.flags:
        print("\nFlags:")
        for fl in sorted(final.flags,
                         key=lambda f: ["CRITICAL","HIGH","MEDIUM","LOW"].index(f.severity)):
            print(f"  [{fl.severity}] {fl.category}")
            print(f"         {fl.description[:110]}")

    rpt = Path("outputs/report.html").resolve()
    print(f"\nReport: file://{rpt}\n")
    if not args.no_browser and rpt.exists():
        webbrowser.open(f"file://{rpt}")


if __name__ == "__main__":
    main()
