"""
Database layer — MongoDB (runs/events) + Neo4j (identity graph).
Both are optional: if credentials missing, silently skips (local JSON still saved).
"""
import logging
from datetime import datetime, timezone
from config import MONGODB_URI, NEO4J_URI, NEO4J_USER, NEO4J_PASS, NEO4J_DATABASE

log = logging.getLogger("db")

# ── MongoDB ────────────────────────────────────────────────────────────────
_mongo_client = None
_mongo_db     = None

def _mongo():
    global _mongo_client, _mongo_db
    if _mongo_db is not None:
        return _mongo_db
    if not MONGODB_URI:
        return None
    try:
        from pymongo import MongoClient
        _mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        _mongo_client.admin.command("ping")
        _mongo_db = _mongo_client["fraud_agent"]
        log.info("MongoDB connected.")
        return _mongo_db
    except Exception as e:
        log.warning(f"MongoDB unavailable: {e}")
        return None


def mongo_save_run(run_id: str, request: dict, events: list[dict]) -> bool:
    db = _mongo()
    if db is None:
        return False
    try:
        complete = next((e for e in reversed(events) if e.get("event") == "complete"), {})
        db["runs"].update_one(
            {"run_id": run_id},
            {"$set": {
                "run_id":       run_id,
                "target":       request.get("target", ""),
                "context":      request.get("context", ""),
                "overall_risk": complete.get("overall_risk", "UNKNOWN"),
                "total_facts":  complete.get("total_facts", 0),
                "total_flags":  complete.get("total_flags", 0),
                "iterations":   complete.get("iterations_run", 0),
                "report":       complete.get("report", {}),
                "graph":        complete.get("graph", {}),
                "events":       events,
                "created_at":   datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        log.info(f"MongoDB: run {run_id} saved.")
        return True
    except Exception as e:
        log.warning(f"MongoDB save failed: {e}")
        return False


def mongo_get_history(limit: int = 50) -> list[dict]:
    db = _mongo()
    if db is None:
        return []
    try:
        return list(db["runs"].find(
            {}, {"run_id": 1, "target": 1, "context": 1, "overall_risk": 1,
                 "total_facts": 1, "total_flags": 1, "created_at": 1, "_id": 0},
            sort=[("created_at", -1)], limit=limit,
        ))
    except Exception as e:
        log.warning(f"MongoDB history failed: {e}")
        return []


def mongo_get_run(run_id: str) -> dict | None:
    db = _mongo()
    if db is None:
        return None
    try:
        return db["runs"].find_one({"run_id": run_id}, {"_id": 0})
    except Exception as e:
        log.warning(f"MongoDB get_run failed: {e}")
        return None


# ── Neo4j ──────────────────────────────────────────────────────────────────
_neo4j_driver = None

def _neo4j():
    global _neo4j_driver
    if _neo4j_driver is not None:
        return _neo4j_driver
    if not NEO4J_URI or not NEO4J_PASS or "xxxxxxxx" in NEO4J_URI or not NEO4J_USER:
        return None
    try:
        from neo4j import GraphDatabase
        _neo4j_driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASS),
        )
        # verify_connectivity() with explicit database
        with _neo4j_driver.session(database=NEO4J_DATABASE) as session:
            session.run("RETURN 1")
        log.info(f"Neo4j connected (database={NEO4J_DATABASE}).")
        return _neo4j_driver
    except Exception as e:
        log.warning(f"Neo4j unavailable: {e}")
        _neo4j_driver = None
        return None


def neo4j_save_graph(run_id: str, target: str, facts: list[dict], flags: list[dict]) -> bool:
    driver = _neo4j()
    if driver is None:
        return False
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            # Clear old data for this run
            session.run("MATCH (n {run_id:$run_id}) DETACH DELETE n", run_id=run_id)

            # Create target node (Entity label for consistent matching)
            session.run(
                "MERGE (n:Entity {name:$name, run_id:$run_id}) "
                "SET n.type='PERSON', n.primary=true",
                name=target, run_id=run_id,
            )

            # Create fact nodes + relationships
            for f in facts:
                subj = f.get("subject", "").strip()
                obj  = f.get("object",  "").strip()
                rel  = f.get("relation", "RELATED_TO").strip().upper().replace(" ", "_")[:50]
                if not subj or not obj:
                    continue
                session.run(
                    "MERGE (a:Entity {name:$subj, run_id:$run_id}) "
                    "MERGE (b:Entity {name:$obj,  run_id:$run_id}) "
                    "MERGE (a)-[r:CONNECTED {relation:$rel, run_id:$run_id}]->(b) "
                    "SET r.confidence=$conf, r.source=$src, r.quote=$quote",
                    subj=subj, obj=obj, rel=rel, run_id=run_id,
                    conf=f.get("confidence", 0.75),
                    src=f.get("source_url", f.get("source", "")),
                    quote=(f.get("quote", "") or "")[:200],
                )

            # Create flag nodes linked to target
            for fl in flags:
                session.run(
                    "MERGE (f:Flag {category:$cat, run_id:$run_id}) "
                    "SET f.severity=$sev, f.description=$desc "
                    "WITH f MATCH (t:Entity {name:$target, run_id:$run_id}) "
                    "MERGE (t)-[:HAS_FLAG]->(f)",
                    cat=fl.get("category", "Unknown"),
                    run_id=run_id,
                    sev=fl.get("severity", "LOW"),
                    desc=(fl.get("description", "") or "")[:500],
                    target=target,
                )

        log.info(f"Neo4j: graph saved for run {run_id} — {len(facts)} facts, {len(flags)} flags.")
        return True
    except Exception as e:
        log.warning(f"Neo4j save failed: {e}")
        return False


def neo4j_get_graph(run_id: str) -> dict:
    driver = _neo4j()
    if driver is None:
        return {"nodes": [], "edges": []}
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            nodes_res = session.run(
                "MATCH (n {run_id:$run_id}) RETURN id(n) as id, labels(n)[0] as label, "
                "n.name as name, n.primary as primary",
                run_id=run_id,
            )
            nodes = [{"id": str(r["id"]), "name": r["name"] or "",
                      "type": r["label"], "primary": bool(r["primary"])}
                     for r in nodes_res]

            edges_res = session.run(
                "MATCH (a {run_id:$run_id})-[r:CONNECTED]->(b {run_id:$run_id}) "
                "RETURN id(a) as from_id, id(b) as to_id, "
                "r.relation as relation, r.confidence as confidence",
                run_id=run_id,
            )
            edges = [{"from": str(r["from_id"]), "to": str(r["to_id"]),
                      "relation": r["relation"], "confidence": r["confidence"]}
                     for r in edges_res]

        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        log.warning(f"Neo4j get_graph failed: {e}")
        return {"nodes": [], "edges": []}


def check_connections() -> dict:
    return {
        "mongodb": _mongo() is not None,
        "neo4j":   _neo4j() is not None,
    }
