"""
Report generation: identity_graph.json, risk_report.json, report.html
"""
import json
import logging
from pathlib import Path
from state import State

OUTPUT = Path("outputs")
OUTPUT.mkdir(exist_ok=True)

log = logging.getLogger("utils")


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(OUTPUT / "run.log", mode="w", encoding="utf-8"),
        ],
    )
    for noisy in ["httpx", "httpcore", "urllib3", "langsmith",
                  "langchain_core", "google"]:
        logging.getLogger(noisy).setLevel(logging.ERROR)


def write_reports(s: State):
    _write_graph(s)
    _write_report(s)
    _write_html(s)
    log.info(f"[OK] Reports in: {OUTPUT.resolve()}")


# ── identity_graph.json ──────────────────────────────────────────────────────
def _write_graph(s: State):
    node_map: dict[str, str] = {}
    nodes, edges = [], []

    def nid(name: str) -> str:
        if name not in node_map:
            node_map[name] = str(len(node_map) + 1)
        return node_map[name]

    # Primary node
    nodes.append({"id": nid(s.target), "name": s.target,
                  "type": "PERSON", "primary": True})

    for f in s.facts:
        if not f.quote:
            continue
        for nm, is_primary in [(f.subject, f.subject == s.target),
                               (f.object,  f.object  == s.target)]:
            if nm and nid(nm) not in [n["id"] for n in nodes]:
                nodes.append({"id": nid(nm), "name": nm,
                              "type": "ENTITY", "primary": is_primary})
        if f.subject and f.object:
            edges.append({
                "from": nid(f.subject), "to": nid(f.object),
                "relation": f.relation,
                "confidence": f.confidence,
                "quote": f.quote[:200],
                "source": f.source_url,
            })

    out = {"subject": s.target, "run_id": s.run_id,
           "nodes": nodes, "edges": edges}
    (OUTPUT / "identity_graph.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    log.info(f"[OK] identity_graph.json: {len(nodes)} nodes, {len(edges)} edges")


# ── risk_report.json ─────────────────────────────────────────────────────────
def _write_report(s: State):
    sevs = [f.severity for f in s.flags]
    overall = next((v for v in ["CRITICAL","HIGH","MEDIUM","LOW"] if v in sevs), "CLEAN")

    report = {
        "subject":        s.target,
        "context":        s.context,
        "run_id":         s.run_id,
        "overall_risk":   overall,
        "iterations_run": s.iteration,
        "aliases":        s.aliases,
        "flags": [f.model_dump() for f in s.flags],
        "key_facts": [
            {"subject": f.subject, "relation": f.relation, "object": f.object,
             "confidence": f.confidence, "source": f.source_url, "quote": f.quote[:300]}
            for f in s.facts if f.quote
        ],
        "total_facts": len(s.facts),
        "total_flags": len(s.flags),
    }
    (OUTPUT / "risk_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    log.info(f"[OK] risk_report.json: overall={overall}, flags={len(s.flags)}, facts={len(s.facts)}")


# ── report.html ──────────────────────────────────────────────────────────────
def _write_html(s: State):
    graph_json  = (OUTPUT / "identity_graph.json").read_text(encoding="utf-8")
    report_json = (OUTPUT / "risk_report.json").read_text(encoding="utf-8")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Report: {s.target}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/dist/vis-network.min.js"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/dist/dist/vis-network.min.css"/>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;padding:24px}}
h1{{font-size:1.6rem;margin-bottom:4px}}
h2{{font-size:1.1rem;color:#8b949e;margin:28px 0 10px}}
.badge{{display:inline-block;padding:4px 12px;border-radius:4px;font-weight:700;font-size:.9rem}}
.CRITICAL{{background:#b91c1c}}.HIGH{{background:#c2410c}}.MEDIUM{{background:#a16207}}.LOW{{background:#166534}}.CLEAN{{background:#1e3a5f}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}}
th{{background:#161b22;color:#8b949e;padding:8px;text-align:left;border-bottom:1px solid #30363d}}
td{{padding:8px;border-bottom:1px solid #21262d;vertical-align:top}}
tr:hover td{{background:#161b22}}
.sev-CRITICAL{{color:#f85149;font-weight:700}}.sev-HIGH{{color:#ff7b72}}.sev-MEDIUM{{color:#e3b341}}.sev-LOW{{color:#56d364}}
a{{color:#58a6ff;text-decoration:none}}
#graph{{width:100%;height:480px;border:1px solid #30363d;border-radius:8px;background:#161b22;margin-top:8px}}
.conf{{background:#21262d;border-radius:3px;height:6px;margin-top:3px}}
.conf-fill{{background:#1f6feb;height:6px;border-radius:3px}}
</style>
</head>
<body>
<h1>Intelligence Report: {s.target}</h1>
<p style="color:#8b949e;margin:4px 0 0">{s.context} &bull; Run: {s.run_id} &bull; {s.iteration} iterations</p>
<div id="risk-badge" style="margin-top:12px"></div>

<h2>Risk Flags</h2>
<table>
<thead><tr><th>Severity</th><th>Category</th><th>Description</th><th>Sources</th></tr></thead>
<tbody id="flags"></tbody>
</table>

<h2>Identity Graph</h2>
<div id="graph"></div>

<h2>Key Facts ({len(s.facts)} total)</h2>
<table>
<thead><tr><th>Subject</th><th>Relation</th><th>Object</th><th>Confidence</th><th>Source</th></tr></thead>
<tbody id="facts"></tbody>
</table>

<script>
const G = {graph_json};
const R = {report_json};

// Badge
const risk = R.overall_risk || "CLEAN";
document.getElementById("risk-badge").innerHTML =
  `<span class="badge ${{risk}}">Overall Risk: ${{risk}}</span>`;

// Flags
const fb = document.getElementById("flags");
(R.flags||[]).forEach(f => {{
  const src = (f.sources||[]).map(s => `<a href="${{s}}" target="_blank">${{s.slice(0,55)}}</a>`).join("<br>");
  fb.innerHTML += `<tr>
    <td class="sev-${{f.severity}}">${{f.severity}}</td>
    <td>${{f.category}}</td>
    <td>${{f.description}}</td>
    <td style="font-size:.75rem">${{src}}</td>
  </tr>`;
}});

// Facts
const ftb = document.getElementById("facts");
(R.key_facts||[]).forEach(f => {{
  const pct = Math.round((f.confidence||0)*100);
  ftb.innerHTML += `<tr>
    <td>${{f.subject}}</td>
    <td style="color:#8b949e">${{f.relation}}</td>
    <td>${{f.object}}</td>
    <td>${{pct}}%<div class="conf"><div class="conf-fill" style="width:${{pct}}%"></div></div></td>
    <td style="font-size:.75rem"><a href="${{f.source}}" target="_blank">${{(f.source||"").slice(0,45)}}</a>
      <br><span style="color:#8b949e">${{(f.quote||"").slice(0,90)}}</span></td>
  </tr>`;
}});

// Graph
const nodes = new vis.DataSet((G.nodes||[]).map(n => ({{
  id: n.id, label: n.name,
  color: n.primary ? {{background:"#1f6feb",border:"#388bfd"}} : {{background:"#21262d",border:"#30363d"}},
  font: {{color:"#e6edf3", size: n.primary?16:12}},
  size: n.primary ? 28 : 16,
}})));
const edges = new vis.DataSet((G.edges||[]).map((e,i) => ({{
  id:i, from:e.from, to:e.to, label:e.relation,
  font:{{color:"#8b949e",size:10,align:"middle"}},
  color:{{color:"#30363d"}}, arrows:"to",
}})));
new vis.Network(document.getElementById("graph"), {{nodes, edges}}, {{
  physics:{{stabilization:{{iterations:120}}}},
  edges:{{smooth:{{type:"curvedCW",roundness:0.2}}}},
}});
</script>
</body>
</html>"""

    (OUTPUT / "report.html").write_text(html, encoding="utf-8")
    log.info("[OK] report.html written")
