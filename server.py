"""
FastAPI backend with SSE streaming.
GET /api/stream?target=...&context=...&max_iterations=8&researcher_model=...
POST /api/run (same params as JSON body — for curl testing)
"""
import json
import time
import uuid
import asyncio
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

from utils import setup_logging
setup_logging()

from state import State, Entity
from graph import run as run_graph
from config import PRIMARY_MODEL, EVALUATOR_MODEL
from main import get_aliases, extract_org
from db import mongo_save_run, mongo_get_history, mongo_get_run, neo4j_save_graph, check_connections

log = logging.getLogger("server")

app = FastAPI(title="Fraud Agent API")
app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"], allow_credentials=True)

RUNS_DIR = Path("outputs/runs")
RUNS_DIR.mkdir(parents=True, exist_ok=True)

_executor = ThreadPoolExecutor(max_workers=4)


def _build_state(target, context, max_iterations, researcher_model, analyst_model, evaluator_model) -> State:
    run_id  = str(uuid.uuid4())[:8]
    aliases = get_aliases(target)
    state   = State(
        run_id=run_id, target=target, context=context, aliases=aliases,
        max_iterations=max_iterations,
        researcher_model=researcher_model or PRIMARY_MODEL,
        analyst_model=analyst_model    or PRIMARY_MODEL,
        evaluator_model=evaluator_model or EVALUATOR_MODEL,
    )
    state.queue.append(Entity(name=target, type="PERSON", priority=10,
                               context=f"Primary target. {context}"))
    org = extract_org(context, target)
    if org:
        state.queue.append(Entity(name=org, type="ORGANIZATION", priority=9,
                                   context=f"Organization linked to {target}."))
    return state


def _make_complete_event(final: State) -> dict:
    node_map: dict[str, str] = {}
    nodes, edges = [], []

    def nid(name: str) -> str:
        if name not in node_map:
            node_map[name] = str(len(node_map) + 1)
        return node_map[name]

    nodes.append({"id": nid(final.target), "name": final.target, "type": "PERSON", "primary": True})
    for f in final.facts:
        if not f.quote:
            continue
        for nm in [f.subject, f.object]:
            if nm and nid(nm) not in [n["id"] for n in nodes]:
                nodes.append({"id": nid(nm), "name": nm, "type": "ENTITY", "primary": False})
        if f.subject and f.object:
            edges.append({"from": nid(f.subject), "to": nid(f.object),
                          "relation": f.relation, "confidence": f.confidence,
                          "quote": f.quote[:200], "source": f.source_url})

    sevs    = [fl.severity for fl in final.flags]
    overall = next((v for v in ["CRITICAL", "HIGH", "MEDIUM", "LOW"] if v in sevs), "CLEAN")

    return dict(
        event="complete",
        overall_risk=overall,
        total_facts=len(final.facts),
        total_flags=len(final.flags),
        iterations_run=final.iteration,
        graph={"nodes": nodes, "edges": edges},
        report={
            "subject": final.target, "context": final.context,
            "overall_risk": overall,
            "flags":     [fl.model_dump() for fl in final.flags],
            "key_facts": [
                {"subject": f.subject, "relation": f.relation, "object": f.object,
                 "confidence": f.confidence, "source": f.source_url, "quote": f.quote[:300]}
                for f in final.facts if f.quote
            ],
            "aliases": final.aliases,
        },
    )


def _sse_stream(state: State):
    """Run the investigation and stream SSE events. Works for both GET and POST."""
    events_log: list[dict] = []
    queue: asyncio.Queue = asyncio.Queue()

    loop = asyncio.get_event_loop()

    def emit(**kw):
        ev = {"run_id": state.run_id, "ts": time.time(), **kw}
        events_log.append(ev)
        loop.call_soon_threadsafe(queue.put_nowait, ev)

    def _run():
        try:
            final = run_graph(state, emit=emit)
            emit(**_make_complete_event(final))
        except Exception as e:
            log.error(f"Run failed: {e}", exc_info=True)
            emit(event="error", message=str(e), recoverable=False)
        finally:
            # Save locally (always)
            req_dict = {"target": state.target, "context": state.context}
            run_file = RUNS_DIR / f"{state.run_id}.json"
            run_file.write_text(json.dumps(
                {"run_id": state.run_id, "request": req_dict, "events": events_log},
                indent=2), encoding="utf-8")
            log.info(f"Run {state.run_id} saved locally.")

            # Save to MongoDB (if configured)
            mongo_save_run(state.run_id, req_dict, events_log)

            # Save graph to Neo4j (if configured)
            complete = next((e for e in reversed(events_log) if e.get("event") == "complete"), {})
            if complete:
                report = complete.get("report", {})
                neo4j_save_graph(
                    state.run_id, state.target,
                    report.get("key_facts", []),
                    report.get("flags", []),
                )

            loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

    async def generator():
        loop.run_in_executor(_executor, _run)
        while True:
            ev = await queue.get()
            if ev is None:
                break
            yield {"data": json.dumps(ev, ensure_ascii=False)}

    return EventSourceResponse(generator())


# ── GET endpoint — works with native EventSource (browser) ─────────────────
@app.get("/api/stream")
async def stream_get(
    target:            str = Query(...),
    context:           str = Query(""),
    max_iterations:    int = Query(8),
    researcher_model:  str = Query(PRIMARY_MODEL),
    analyst_model:     str = Query(PRIMARY_MODEL),
    evaluator_model:   str = Query(EVALUATOR_MODEL),
):
    state = _build_state(target, context, max_iterations,
                         researcher_model, analyst_model, evaluator_model)
    return _sse_stream(state)


# ── POST endpoint — for programmatic use / curl testing ────────────────────
class RunRequest(BaseModel):
    target: str
    context: str = ""
    max_iterations: int = 8
    researcher_model: str = PRIMARY_MODEL
    analyst_model:    str = PRIMARY_MODEL
    evaluator_model:  str = EVALUATOR_MODEL


@app.post("/api/run")
async def run_post(req: RunRequest):
    state = _build_state(req.target, req.context, req.max_iterations,
                         req.researcher_model, req.analyst_model, req.evaluator_model)
    return _sse_stream(state)


@app.get("/api/history")
def history():
    # Try MongoDB first
    mongo_runs = mongo_get_history(50)
    if mongo_runs:
        for r in mongo_runs:
            if "created_at" in r:
                r["ts"] = r["created_at"].timestamp() if hasattr(r["created_at"], "timestamp") else 0
                del r["created_at"]
        return mongo_runs

    # Fallback: local JSON files
    runs = []
    for f in sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            complete = next((e for e in reversed(data["events"]) if e.get("event") == "complete"), {})
            runs.append({
                "run_id":       data["run_id"],
                "target":       data["request"]["target"],
                "context":      data["request"].get("context", ""),
                "overall_risk": complete.get("overall_risk", "RUNNING"),
                "total_flags":  complete.get("total_flags", 0),
                "total_facts":  complete.get("total_facts", 0),
                "ts":           data["events"][0]["ts"] if data["events"] else 0,
            })
        except Exception:
            pass
    return runs


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    # Try MongoDB first
    mongo_doc = mongo_get_run(run_id)
    if mongo_doc:
        return mongo_doc

    # Fallback: local JSON
    f = RUNS_DIR / f"{run_id}.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    return json.loads(f.read_text(encoding="utf-8"))


@app.get("/api/db-status")
def db_status():
    return check_connections()


@app.get("/api/models")
def get_models():
    from config import OPENAI_API_KEY, ANTHROPIC_API_KEY, GROQ_API_KEY
    models = [
        {"id": "gemini-3.1-flash-lite-preview",                   "label": "Gemini Flash Lite",    "available": True},
        {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "label": "LLaMA 4 Scout (Groq)", "available": bool(GROQ_API_KEY)},
        {"id": "gpt-4o-mini",                                      "label": "GPT-4o Mini (OpenAI)", "available": bool(OPENAI_API_KEY)},
        {"id": "gpt-4.1-mini",                                     "label": "GPT-4.1 Mini",         "available": bool(OPENAI_API_KEY)},
        {"id": "claude-haiku-4-5-20251001",                        "label": "Claude Haiku 4.5",     "available": bool(ANTHROPIC_API_KEY)},
        {"id": "claude-sonnet-4-6",                                "label": "Claude Sonnet 4.6",    "available": bool(ANTHROPIC_API_KEY)},
    ]
    return {"models": models}
