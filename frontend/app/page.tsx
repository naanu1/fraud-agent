"use client";
import { useState, useEffect, useRef, useCallback } from "react";

const API = "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────
type Ev = Record<string, unknown> & { event: string; ts?: number; iteration?: number };

interface HistoryItem {
  run_id: string; target: string; context: string;
  overall_risk: string; total_flags: number; total_facts: number; ts: number;
}
interface RunParams {
  target: string; context: string; maxIter: number;
  models: { researcher: string; analyst: string; evaluator: string };
}

const MODELS = [
  { id: "gemini-3.1-flash-lite-preview", label: "Gemma 4 26B (Primary)" },
  { id: "llama-3.1-8b-instant", label: "LLaMA 4 Scout (Groq)" },
];
const AGENT_META = {
  researcher: { icon: "R", color: "#388bfd", label: "Researcher" },
  analyst: { icon: "A", color: "#a371f7", label: "Analyst" },
  evaluator: { icon: "E", color: "#3fb950", label: "Evaluator" },
} as const;

const NODE_COLORS: Record<string, { bg: string; border: string; font: string }> = {
  PERSON: { bg: "#1a3a5c", border: "#388bfd", font: "#58a6ff" },
  ORGANIZATION: { bg: "#2d1b4e", border: "#a371f7", font: "#c084fc" },
  COMPANY: { bg: "#2d1b4e", border: "#a371f7", font: "#c084fc" },
  FLAG: { bg: "#4a1f1f", border: "#f85149", font: "#ff6b6b" },
  LOCATION: { bg: "#1a3a2a", border: "#3fb950", font: "#56d364" },
  EVENT: { bg: "#3a2a10", border: "#e3b341", font: "#f0c040" },
  DEFAULT: { bg: "#21262d", border: "#484f58", font: "#8b949e" },
};

// ── Tiny helpers ───────────────────────────────────────────────────────────
function Badge({ risk }: { risk: string }) {
  const colors: Record<string, { bg: string; color: string }> = {
    CRITICAL: { bg: "rgba(248,81,73,0.15)", color: "#f85149" },
    HIGH: { bg: "rgba(210,153,34,0.15)", color: "#d97706" },
    MEDIUM: { bg: "rgba(227,179,65,0.15)", color: "#e3b341" },
    LOW: { bg: "rgba(86,211,100,0.15)", color: "#56d364" },
    CLEAN: { bg: "rgba(86,211,100,0.15)", color: "#56d364" },
  };
  const c = colors[risk] || colors.CLEAN;
  return (
    <span style={{
      padding: "2px 10px", borderRadius: 4, fontSize: 11, fontWeight: 700,
      background: c.bg, color: c.color, border: `1px solid ${c.color}44`,
    }}>{risk}</span>
  );
}
function Dots() {
  return (
    <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
      <span className="thinking-dot" /><span className="thinking-dot" /><span className="thinking-dot" />
    </span>
  );
}
function Label({ children }: { children: string }) {
  return (
    <label style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1 }}>
      {children}
    </label>
  );
}
function SevBadge({ sev }: { sev: string }) {
  const s = (sev || "").toUpperCase();
  const colors: Record<string, { bg: string; color: string }> = {
    CRITICAL: { bg: "rgba(248,81,73,0.15)", color: "#f85149" },
    HIGH: { bg: "rgba(210,153,34,0.15)", color: "#d97706" },
    MEDIUM: { bg: "rgba(227,179,65,0.15)", color: "#e3b341" },
    LOW: { bg: "rgba(86,211,100,0.15)", color: "#56d364" },
  };
  const c = colors[s] || colors.LOW;
  return (
    <span style={{
      fontSize: 10, padding: "2px 7px", borderRadius: 3, fontWeight: 700,
      background: c.bg, color: c.color, border: `1px solid ${c.color}44`,
    }}>{s}</span>
  );
}
function ToolBadge({ tool }: { tool: string }) {
  const t = (tool || "").toUpperCase();
  const map: Record<string, { bg: string; color: string }> = {
    TAVILY: { bg: "rgba(88,166,255,0.15)", color: "#58a6ff" },
    SERPER: { bg: "rgba(163,113,247,0.15)", color: "#c084fc" },
    SANCTIONS: { bg: "rgba(86,211,100,0.15)", color: "#56d364" },
  };
  const c = map[t] || { bg: "rgba(139,148,158,0.15)", color: "#8b949e" };
  return (
    <span style={{
      fontSize: 9, padding: "1px 5px", borderRadius: 3, fontWeight: 700, flexShrink: 0,
      background: c.bg, color: c.color, border: `1px solid ${c.color}44`,
    }}>{t}</span>
  );
}

// ── Sidebar ────────────────────────────────────────────────────────────────
function Sidebar({ onRun, running, history, onReplay }: {
  onRun: (p: RunParams) => void; running: boolean;
  history: HistoryItem[]; onReplay: (id: string) => void;
}) {
  const [target, setTarget] = useState("");
  const [context, setContext] = useState("");
  const [maxIter, setMaxIter] = useState(8);
  const [models, setModels] = useState({
    researcher: MODELS[0].id, analyst: MODELS[0].id, evaluator: MODELS[0].id,
  });

  return (
    <aside style={{
      width: 276, minWidth: 276, background: "var(--surface)",
      borderRight: "1px solid var(--border)", display: "flex",
      flexDirection: "column", height: "100%", overflowY: "auto", flexShrink: 0,
    }}>
      <div style={{ padding: "18px 18px 14px", borderBottom: "1px solid var(--border)" }}>
        <div style={{ fontSize: 17, fontWeight: 700, letterSpacing: "-0.5px" }}>
          <span style={{ color: "var(--accent)" }}>◈</span> IntelliAgent
        </div>
        <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>Autonomous Research System</div>
      </div>

      <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 14 }}>
        <div>
          <Label>Investigation Target</Label>
          <input value={target} onChange={e => setTarget(e.target.value)}
            placeholder="e.g. Timothy Overturf" disabled={running}
            style={{
              width: "100%", marginTop: 6, padding: "8px 10px", background: "var(--bg)",
              border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)",
              fontSize: 13, outline: "none", boxSizing: "border-box",
            }} />
        </div>
        <div>
          <Label>Context</Label>
          <input value={context} onChange={e => setContext(e.target.value)}
            placeholder="e.g. CEO of Sisu Capital" disabled={running}
            style={{
              width: "100%", marginTop: 6, padding: "8px 10px", background: "var(--bg)",
              border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)",
              fontSize: 13, outline: "none", boxSizing: "border-box",
            }} />
        </div>

        <div>
          <Label>Agent Models</Label>
          {(["researcher", "analyst", "evaluator"] as const).map(a => (
            <div key={a} style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
              <span style={{
                width: 24, height: 24, borderRadius: 6, fontSize: 11, fontWeight: 700, flexShrink: 0,
                background: AGENT_META[a].color + "22", color: AGENT_META[a].color,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>{AGENT_META[a].icon}</span>
              <select value={models[a]} disabled={running}
                onChange={e => setModels(m => ({ ...m, [a]: e.target.value }))}
                style={{
                  flex: 1, padding: "5px 8px", background: "var(--bg)",
                  border: "1px solid var(--border)", borderRadius: 6,
                  color: "var(--text)", fontSize: 12, outline: "none",
                }}>
                {MODELS.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
            </div>
          ))}
        </div>

        <div>
          <Label>Max Iterations: </Label>
          <span style={{ color: "var(--accent)", fontSize: 12, marginLeft: 4 }}>{maxIter}</span>
          <input type="range" min={2} max={15} value={maxIter}
            onChange={e => setMaxIter(Number(e.target.value))} disabled={running}
            style={{ width: "100%", marginTop: 8, accentColor: "var(--accent)" }} />
        </div>

        <button
          onClick={() => { if (!running && target.trim()) onRun({ target, context, maxIter, models }); }}
          disabled={running || !target.trim()}
          style={{
            padding: "10px 0", border: "none", borderRadius: 8, fontWeight: 600, fontSize: 14,
            background: running ? "var(--surface2)" : "var(--accent)",
            color: "white", cursor: running || !target.trim() ? "not-allowed" : "pointer",
            transition: "background 0.2s", opacity: !target.trim() ? 0.5 : 1,
          }}>
          {running
            ? <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
              <Dots /> Running...
            </span>
            : "▶  Run Investigation"}
        </button>
      </div>

      <div style={{ borderTop: "1px solid var(--border)", padding: "12px 16px", flex: 1, overflowY: "auto" }}>
        <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1, marginBottom: 10 }}>
          History
        </div>
        {history.length === 0 && <div style={{ color: "var(--muted)", fontSize: 12 }}>No runs yet.</div>}
        {history.map(h => (
          <div key={h.run_id} onClick={() => onReplay(h.run_id)}
            style={{
              padding: "8px 10px", marginBottom: 4, borderRadius: 6, cursor: "pointer",
              background: "var(--bg)", border: "1px solid var(--border)", transition: "border-color 0.15s",
            }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--accent)")}
            onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--border)")}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: 600, fontSize: 12 }}>{h.target}</span>
              <Badge risk={h.overall_risk} />
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
              {h.total_flags} flags · {h.total_facts} facts · #{h.run_id.slice(0, 8)}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}

// ── Researcher Card body ───────────────────────────────────────────────────
function ResearcherBody({ iter, events, isRunning }: { iter: number; events: Ev[]; isRunning: boolean }) {
  const queries = events.filter(e => e.event === "query_executed" && e.iteration === iter);
  const logs = events.filter(e => e.event === "agent_log" && e.agent === "researcher" && e.iteration === iter);
  const llmIn = events.find(e => e.event === "llm_input" && e.agent === "researcher" && e.iteration === iter);

  return (
    <div style={{ padding: "8px 14px 12px", borderTop: "1px solid var(--border)" }}>
      {llmIn && (
        <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 8 }}>
          Prompt: <b style={{ color: "var(--accent)" }}>{((llmIn.full_prompt as string) || "").length.toLocaleString()} chars</b>
        </div>
      )}

      {queries.length === 0 && logs.length === 0 && isRunning && (
        <div style={{ color: "var(--muted)", fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <Dots /> Building search plan...
        </div>
      )}

      {queries.filter(q => q.status === "ok").map((q, i) => (
        <div key={i} style={{
          display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 6,
          padding: "6px 8px", background: "var(--bg)", borderRadius: 6,
          border: "1px solid var(--border)",
        }}>
          <ToolBadge tool={q.tool as string} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, color: "var(--text)", wordBreak: "break-word" }}>
              {q.query as string}
            </div>
            <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 2 }}>
              {(q.result_chars as number)?.toLocaleString()} chars fetched
            </div>
          </div>
          <span style={{ fontSize: 11, flexShrink: 0, color: "var(--low)" }}>✓</span>
        </div>
      ))}

      {logs.map((l, i) => (
        <div key={i} style={{ fontSize: 11, color: "var(--muted)", marginTop: 4, paddingLeft: 4 }}>
          › {l.message as string}
        </div>
      ))}
    </div>
  );
}

// ── Analyst Card body ──────────────────────────────────────────────────────
function AnalystBody({ iter, events, isRunning }: { iter: number; events: Ev[]; isRunning: boolean }) {
  const facts = events.filter(e => e.event === "fact_found" && e.iteration === iter);
  const entities = events.filter(e => e.event === "entity_found" && e.iteration === iter);
  const logs = events.filter(e => e.event === "agent_log" && e.agent === "analyst" && e.iteration === iter);
  const llmOut = events.find(e => e.event === "llm_output" && e.agent === "analyst" && e.iteration === iter);

  return (
    <div style={{ padding: "8px 14px 12px", borderTop: "1px solid var(--border)" }}>
      {llmOut && (
        <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 8 }}>
          <b style={{ color: "var(--text)" }}>{llmOut.full_output as string}</b>
        </div>
      )}

      {facts.length === 0 && logs.length === 0 && isRunning && (
        <div style={{ color: "var(--muted)", fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <Dots /> Extracting facts...
        </div>
      )}

      {facts.map((f, i) => {
        const conf = (f.confidence as number) || 0;
        const confPct = Math.round(conf * 100);
        const confColor = confPct >= 90 ? "var(--low)" : confPct >= 70 ? "var(--medium)" : "var(--muted)";
        return (
          <div key={i} className="animate-fade-in" style={{
            marginBottom: 6, padding: "8px 10px", background: "var(--bg)", borderRadius: 6,
            border: "1px solid var(--border)", borderLeft: "3px solid var(--accent)",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", fontSize: 12 }}>
              <span style={{ fontWeight: 600, color: "var(--text)" }}>{f.subject as string}</span>
              <span style={{ color: "var(--muted)", fontSize: 11 }}>→</span>
              <span style={{ color: "var(--accent)", fontStyle: "italic" }}>{f.relation as string}</span>
              <span style={{ color: "var(--muted)", fontSize: 11 }}>→</span>
              <span style={{ color: "var(--text)" }}>{f.object as string}</span>
              <span style={{ marginLeft: "auto", fontSize: 10, color: confColor, flexShrink: 0 }}>{confPct}%</span>
            </div>
            {!!f.quote && (
              <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4, fontStyle: "italic", borderLeft: "2px solid var(--border)", paddingLeft: 6 }}>
                &ldquo;{(f.quote as string).slice(0, 120)}{(f.quote as string).length > 120 ? "…" : ""}&rdquo;
              </div>
            )}
            {!!(f.source_url || f.source) && (
              <div style={{ marginTop: 3 }}>
                <a href={(f.source_url || f.source) as string} target="_blank" rel="noreferrer"
                  style={{ fontSize: 10, color: "var(--accent)", textDecoration: "none" }}>
                  ↗ {((f.source_url || f.source) as string).replace(/^https?:\/\//, "").slice(0, 60)}
                </a>
              </div>
            )}
          </div>
        );
      })}

      {entities.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 }}>New Leads</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {entities.map((e, i) => (
              <span key={i} style={{
                fontSize: 11, padding: "2px 8px", borderRadius: 4,
                background: "rgba(88,166,255,0.1)", color: "var(--clean)",
                border: "1px solid rgba(88,166,255,0.2)",
              }}>+ {e.name as string} <span style={{ color: "var(--muted)", fontSize: 10 }}>({e.entity_type as string})</span></span>
            ))}
          </div>
        </div>
      )}

      {logs.map((l, i) => (
        <div key={i} style={{ fontSize: 11, color: "var(--muted)", marginTop: 4, paddingLeft: 4 }}>
          › {l.message as string}
        </div>
      ))}
    </div>
  );
}

// ── Evaluator Card body ────────────────────────────────────────────────────
function EvaluatorBody({ iter, events, isRunning }: { iter: number; events: Ev[]; isRunning: boolean }) {
  const flags = events.filter(e => e.event === "flag_found" && e.iteration === iter);
  const nextQ = events.find(e => e.event === "next_queries" && e.iteration === iter);
  const logs = events.filter(e => e.event === "agent_log" && e.agent === "evaluator" && e.iteration === iter);
  const iterEnd = events.find(e => e.event === "iteration_start" && (e.iteration as number) === iter + 1);
  const complete = events.find(e => e.event === "complete");
  const isLast = !iterEnd && !!complete;
  const routing = ((nextQ?.suggested_queries || nextQ?.queries) as string[] | undefined) || [];
  const decision = isLast ? "STOP" : routing.length > 0 ? "CONTINUE" : null;

  return (
    <div style={{ padding: "8px 14px 12px", borderTop: "1px solid var(--border)" }}>
      {flags.length === 0 && logs.length === 0 && isRunning && (
        <div style={{ color: "var(--muted)", fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <Dots /> Evaluating risks...
        </div>
      )}

      {flags.map((fl, i) => (
        <div key={i} className="animate-fade-in" style={{
          marginBottom: 6, padding: "8px 10px", borderRadius: 6, fontSize: 12,
          background: "rgba(248,81,73,0.06)", border: "1px solid rgba(248,81,73,0.2)",
          borderLeft: "3px solid var(--critical)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
            <SevBadge sev={fl.severity as string} />
            <span style={{ fontWeight: 600, color: "var(--high)" }}>{fl.category as string}</span>
          </div>
          <div style={{ color: "var(--muted)", fontSize: 11 }}>{fl.description as string}</div>
        </div>
      ))}

      {decision && (
        <div style={{
          marginTop: 8, padding: "8px 10px", borderRadius: 6,
          background: decision === "CONTINUE" ? "rgba(63,185,80,0.08)" : "rgba(88,166,255,0.08)",
          border: `1px solid ${decision === "CONTINUE" ? "rgba(63,185,80,0.25)" : "rgba(88,166,255,0.25)"}`,
          fontSize: 12,
        }}>
          <span style={{ fontWeight: 700, color: decision === "CONTINUE" ? "var(--low)" : "var(--accent)" }}>
            {decision === "CONTINUE" ? "▶ CONTINUE" : "■ STOP — Investigation complete"}
          </span>
          {routing.length > 0 && decision === "CONTINUE" && (
            <div style={{ marginTop: 6 }}>
              <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 }}>Next queries</div>
              {routing.slice(0, 4).map((q, i) => (
                <div key={i} style={{ fontSize: 11, color: "var(--muted)", paddingLeft: 8, marginBottom: 2 }}>
                  → {q}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {logs.map((l, i) => (
        <div key={i} style={{ fontSize: 11, color: "var(--muted)", marginTop: 4, paddingLeft: 4 }}>
          › {l.message as string}
        </div>
      ))}
    </div>
  );
}

// ── Agent Card ─────────────────────────────────────────────────────────────
function AgentCard({ agent, iter, events }: { agent: keyof typeof AGENT_META; iter: number; events: Ev[] }) {
  const [open, setOpen] = useState(true);
  const meta = AGENT_META[agent];
  const start = events.find(e => e.event === "agent_start" && e.agent === agent && e.iteration === iter);
  const end = events.find(e => e.event === "agent_end" && e.agent === agent && e.iteration === iter);
  const facts = events.filter(e => e.event === "fact_found" && e.iteration === iter);
  const flags = events.filter(e => e.event === "flag_found" && e.iteration === iter);
  const entities = events.filter(e => e.event === "entity_found" && e.iteration === iter);
  const queries = events.filter(e => e.event === "query_executed" && e.iteration === iter);

  if (!start) return null;
  const running = !end;

  return (
    <div className="animate-slide-in" style={{
      background: "var(--surface)", borderRadius: 10, overflow: "hidden", marginBottom: 8,
      border: "1px solid var(--border)", borderLeft: `3px solid ${meta.color}`,
    }}>
      <div onClick={() => setOpen(o => !o)} style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "10px 14px", cursor: "pointer", userSelect: "none",
      }}>
        <span style={{
          width: 28, height: 28, borderRadius: 8, fontSize: 13, fontWeight: 700, flexShrink: 0,
          background: meta.color + "22", color: meta.color,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>{meta.icon}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{meta.label}</div>
          <div style={{ fontSize: 11, color: "var(--muted)" }}>
            {start.model as string}
            {agent === "researcher" && queries.length > 0 && ` · ${queries.length} searches`}
            {agent === "analyst" && facts.length > 0 && ` · ${facts.length} facts`}
            {agent === "evaluator" && flags.length > 0 && ` · ${flags.length} flags`}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {agent === "analyst" && facts.length > 0 && (
            <span style={{ fontSize: 11, padding: "1px 7px", borderRadius: 4, background: "rgba(86,211,100,0.12)", color: "var(--low)" }}>
              +{facts.length} facts
            </span>
          )}
          {agent === "evaluator" && flags.length > 0 && (
            <span style={{ fontSize: 11, padding: "1px 7px", borderRadius: 4, background: "rgba(248,81,73,0.12)", color: "var(--critical)" }}>
              {flags.length} flags
            </span>
          )}
          {agent === "analyst" && entities.length > 0 && (
            <span style={{ fontSize: 11, padding: "1px 7px", borderRadius: 4, background: "rgba(88,166,255,0.12)", color: "var(--clean)" }}>
              +{entities.length} entities
            </span>
          )}
          {running ? <Dots /> : <span style={{ color: "var(--low)", fontSize: 15 }}>✓</span>}
          <span style={{ color: "var(--muted)", fontSize: 11 }}>{open ? "▲" : "▼"}</span>
        </div>
      </div>

      {open && (
        agent === "researcher" ? <ResearcherBody iter={iter} events={events} isRunning={running} /> :
          agent === "analyst" ? <AnalystBody iter={iter} events={events} isRunning={running} /> :
            <EvaluatorBody iter={iter} events={events} isRunning={running} />
      )}
    </div>
  );
}

// ── Iteration block ─────────────────────────────────────────────────────────
function IterBlock({ iter, events }: { iter: number; events: Ev[] }) {
  const iterStart = events.find(e => e.event === "iteration_start" && e.iteration === iter);
  const riskSoFar = iterStart?.current_risk as string | undefined;
  return (
    <div className="animate-slide-in" style={{ marginBottom: 16 }}>
      <div style={{
        fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1,
        marginBottom: 8, display: "flex", alignItems: "center", gap: 8,
      }}>
        <span style={{ flex: 1, height: 1, background: "var(--border)" }} />
        <span>Iteration {iter}</span>
        {riskSoFar && riskSoFar !== "CLEAN" && (
          <Badge risk={riskSoFar} />
        )}
        <span style={{ flex: 1, height: 1, background: "var(--border)" }} />
      </div>
      {(["researcher", "analyst", "evaluator"] as const).map(a => (
        <AgentCard key={a} agent={a} iter={iter} events={events} />
      ))}
    </div>
  );
}

// ── User View ──────────────────────────────────────────────────────────────
function UserView({ events }: { events: Ev[] }) {
  const iters = [...new Set(events.map(e => e.iteration).filter(i => i != null && i !== undefined))] as number[];
  if (iters.length === 0) return (
    <div style={{ color: "var(--muted)", textAlign: "center", marginTop: 100, fontSize: 14 }}>
      Enter a name in the sidebar and click <b style={{ color: "var(--text)" }}>Run Investigation</b>.
    </div>
  );
  return <>{iters.sort((a, b) => a - b).map(i => <IterBlock key={i} iter={i} events={events} />)}</>;
}

// ── LLM Calls Panel ────────────────────────────────────────────────────────
function LLMCallsPanel({ events }: { events: Ev[] }) {
  const [exp, setExp] = useState<string | null>(null);
  const llmIns = events.filter(e => e.event === "llm_input");
  const llmOuts = events.filter(e => e.event === "llm_output");
  if (llmIns.length === 0) return null;

  return (
    <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
      <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1, marginBottom: 8 }}>
        LLM Calls ({llmIns.length} calls)
      </div>
      {llmIns.map((inp, i) => {
        const agent = inp.agent as string;
        const iter = inp.iteration as number;
        const key = `${iter}-${agent}`;
        const out = llmOuts.find(e => e.agent === agent && e.iteration === iter);
        const isExp = exp === key;
        const fullPrompt = (inp.full_prompt as string) || "";
        const fullOutput = (out?.full_output as string) || "";
        const agentColor = AGENT_META[agent as keyof typeof AGENT_META]?.color || "#8b949e";

        return (
          <div key={key + i} style={{ marginBottom: 6, border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden" }}>
            <div onClick={() => setExp(isExp ? null : key)}
              style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", cursor: "pointer", background: "var(--bg)", fontSize: 11 }}>
              <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3, background: agentColor + "22", color: agentColor, fontWeight: 700 }}>
                {agent?.toUpperCase()}
              </span>
              <span style={{ color: "var(--muted)" }}>Iter {iter}</span>
              <span style={{ color: "var(--accent)", marginLeft: 4 }}>{fullPrompt.length.toLocaleString()} chars in</span>
              {out && <span style={{ color: "var(--low)", marginLeft: 4 }}>{fullOutput.length.toLocaleString()} chars out</span>}
              <span style={{ marginLeft: "auto", color: "var(--muted)" }}>{isExp ? "▲" : "▼"}</span>
            </div>
            {isExp && (
              <div style={{ borderTop: "1px solid var(--border)" }}>
                {/* Full prompt */}
                <div style={{ padding: "6px 10px", background: "var(--surface2)", fontSize: 10, color: "#a371f7", fontWeight: 600, textTransform: "uppercase", letterSpacing: 1 }}>
                  ↓ INPUT TO LLM ({fullPrompt.length.toLocaleString()} chars)
                </div>
                <pre style={{ fontSize: 11, padding: "8px 12px", background: "var(--bg)", overflowX: "auto", color: "var(--text)", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 320, overflowY: "auto", margin: 0 }}>
                  {fullPrompt || "(no prompt captured)"}
                </pre>
                {/* Full output */}
                <div style={{ padding: "6px 10px", background: "var(--surface2)", fontSize: 10, color: "#3fb950", fontWeight: 600, textTransform: "uppercase", letterSpacing: 1, borderTop: "1px solid var(--border)" }}>
                  ↑ OUTPUT FROM LLM ({fullOutput.length.toLocaleString()} chars)
                </div>
                <pre style={{ fontSize: 11, padding: "8px 12px", background: "var(--bg)", overflowX: "auto", color: "var(--text)", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 320, overflowY: "auto", margin: 0 }}>
                  {fullOutput || "(output pending or not captured)"}
                </pre>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Dev View ───────────────────────────────────────────────────────────────
const EV_COLORS: Record<string, string> = {
  iteration_start: "#58a6ff", agent_start: "#a371f7", agent_end: "#8b949e",
  agent_log: "#c9d1d9", query_executed: "#388bfd", fact_found: "#56d364",
  flag_found: "#f85149", entity_found: "#e3b341", llm_input: "#a371f7",
  llm_output: "#3fb950", next_queries: "#ff7b72", complete: "#56d364", error: "#f85149",
};

function DevView({ events }: { events: Ev[] }) {
  const [exp, setExp] = useState<number | null>(null);

  // Character counts from llm_input/llm_output events (backend emits full_prompt / full_output strings)
  const inTok = events.filter(e => e.event === "llm_input").reduce((s, e) => {
    return s + ((e.input_tokens as number) || (e.full_prompt as string || "").length || 0);
  }, 0);
  const outTok = events.filter(e => e.event === "llm_output").reduce((s, e) => {
    return s + ((e.output_tokens as number) || (e.full_output as string || "").length || 0);
  }, 0);

  // Tool latency from query_executed events
  const queryEvents = events.filter(e => e.event === "query_executed");
  const toolStats: Record<string, { count: number; totalChars: number }> = {};
  for (const q of queryEvents) {
    const t = (q.tool as string) || "unknown";
    if (!toolStats[t]) toolStats[t] = { count: 0, totalChars: 0 };
    toolStats[t].count++;
    toolStats[t].totalChars += (q.result_chars as number) || 0;
  }

  // Next queries / routing
  const nextQEvs = events.filter(e => e.event === "next_queries");
  const totalFetched = queryEvents.reduce((s, q) => s + ((q.result_chars as number) || 0), 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Stats bar */}
      <div style={{
        padding: "6px 14px", background: "var(--surface2)", borderBottom: "1px solid var(--border)",
        display: "flex", gap: 20, fontSize: 12, color: "var(--muted)", flexShrink: 0, flexWrap: "wrap",
      }}>
        <span>Events: <b style={{ color: "var(--text)" }}>{events.length}</b></span>
        <span>In: <b style={{ color: "var(--accent)" }}>{inTok.toLocaleString()} chars</b></span>
        <span>Out: <b style={{ color: "var(--low)" }}>{outTok.toLocaleString()} chars</b></span>
        <span>Fetched: <b style={{ color: "var(--medium)" }}>{totalFetched.toLocaleString()} chars</b></span>
        <span>Searches: <b style={{ color: "var(--text)" }}>{queryEvents.length}</b></span>
      </div>

      <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 0 }}>
        {/* Tool matrix */}
        {Object.keys(toolStats).length > 0 && (
          <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
            <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>Tool Execution</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {Object.entries(toolStats).map(([tool, stat]) => (
                <div key={tool} style={{
                  padding: "4px 10px", borderRadius: 6, background: "var(--bg)",
                  border: "1px solid var(--border)", fontSize: 11,
                }}>
                  <ToolBadge tool={tool} />
                  <span style={{ marginLeft: 6, color: "var(--text)" }}>{stat.count}×</span>
                  <span style={{ marginLeft: 4, color: "var(--muted)" }}>{stat.totalChars.toLocaleString()} chars</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* LLM Calls — full input/output per iteration per agent */}
        <LLMCallsPanel events={events} />

        {/* Routing decisions */}
        {nextQEvs.length > 0 && (
          <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
            <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>Routing Decisions (Agent 3 → Agent 1)</div>
            {nextQEvs.map((nq, i) => {
              const qs = ((nq.suggested_queries || nq.queries) as string[] | undefined) || [];
              return (
                <div key={i} style={{ marginBottom: 8, padding: "6px 8px", background: "var(--bg)", borderRadius: 6, border: "1px solid var(--border)", fontSize: 11 }}>
                  <span style={{ color: "var(--muted)" }}>Iter {nq.iteration}: </span>
                  <span style={{ color: "var(--low)", fontWeight: 600 }}>CONTINUE</span>
                  <span style={{ color: "var(--muted)" }}> — {qs.length} queries injected into Agent 1</span>
                  {qs.map((q, j) => (
                    <div key={j} style={{ color: "var(--accent)", marginTop: 3, paddingLeft: 8 }}>→ {q}</div>
                  ))}
                </div>
              );
            })}
          </div>
        )}

        {/* Event stream */}
        <div style={{ flex: 1, overflowY: "auto", padding: 8 }}>
          {events.length === 0 && (
            <div style={{ color: "var(--muted)", padding: 24, textAlign: "center" }}>No events yet.</div>
          )}
          {events.map((ev, i) => {
            const ts = ev.ts ? new Date((ev.ts as number) * 1000).toLocaleTimeString() : "";
            const col = EV_COLORS[ev.event] || "var(--muted)";
            const { event, run_id: _r, ts: _t, ...rest } = ev;
            const preview = Object.entries(rest).slice(0, 2)
              .map(([k, v]) => `${k}: ${JSON.stringify(v)?.slice(0, 45)}`).join("  ");
            const isExp = exp === i;
            return (
              <div key={i} className="animate-fade-in" style={{ marginBottom: 1 }}>
                <div onClick={() => setExp(isExp ? null : i)} style={{
                  display: "flex", gap: 8, alignItems: "center", padding: "3px 8px",
                  borderRadius: 4, cursor: "pointer", fontSize: 12,
                  background: isExp ? "var(--surface2)" : "transparent",
                }}
                  onMouseEnter={e => !isExp && (e.currentTarget.style.background = "var(--surface)")}
                  onMouseLeave={e => !isExp && (e.currentTarget.style.background = "transparent")}>
                  <span style={{ color: "var(--muted)", fontSize: 10, flexShrink: 0, width: 68 }}>{ts}</span>
                  <span style={{
                    fontSize: 10, padding: "1px 7px", borderRadius: 3, flexShrink: 0,
                    background: col + "22", color: col, border: `1px solid ${col}44`,
                    minWidth: 120, textAlign: "center",
                  }}>{event}</span>
                  <span style={{ color: "var(--muted)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {preview}
                  </span>
                </div>
                {isExp && (
                  <pre style={{
                    fontSize: 11, padding: "8px 12px", background: "var(--bg)", borderRadius: 6,
                    margin: "2px 8px 4px", overflowX: "auto", color: "var(--text)",
                    border: "1px solid var(--border)", whiteSpace: "pre-wrap", wordBreak: "break-all",
                  }}>
                    {JSON.stringify(ev, null, 2)}
                  </pre>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Graph ──────────────────────────────────────────────────────────────────
function Graph({ graph }: { graph: { nodes: unknown[]; edges: unknown[] } }) {
  const ref = useRef<HTMLDivElement>(null);
  const netRef = useRef<unknown>(null);

  useEffect(() => {
    if (!ref.current || !graph?.nodes?.length) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const vis = (window as any).vis;
    if (!vis) return;

    // Destroy existing network
    if (netRef.current) {
      (netRef.current as { destroy(): void }).destroy();
      netRef.current = null;
    }

    const nodes = new vis.DataSet(graph.nodes.map((n: unknown) => {
      const nd = n as Record<string, unknown>;
      const ntype = ((nd.node_type || nd.type || "DEFAULT") as string).toUpperCase();
      const c = NODE_COLORS[ntype] || NODE_COLORS.DEFAULT;
      const isPrimary = !!nd.primary;
      return {
        id: nd.id,
        label: nd.name as string,
        title: `${ntype}\n${nd.name}`,
        color: { background: c.bg, border: c.border, highlight: { background: c.bg, border: c.font } },
        font: { color: c.font, size: isPrimary ? 15 : 11, face: "monospace" },
        size: isPrimary ? 32 : 18,
        shape: isPrimary ? "star" : ntype === "FLAG" ? "diamond" : ntype === "ORGANIZATION" || ntype === "COMPANY" ? "box" : "dot",
        borderWidth: isPrimary ? 3 : 1.5,
        shadow: isPrimary ? { enabled: true, color: c.border + "88", size: 12 } : false,
      };
    }));

    const edges = new vis.DataSet((graph.edges as Record<string, unknown>[]).map((e, i) => {
      const conf = (e.confidence as number) || 0.5;
      return {
        id: i,
        from: e.from,
        to: e.to,
        label: e.relation as string,
        font: { color: "#8b949e", size: 9, face: "monospace", align: "middle" },
        color: { color: "#484f58", highlight: "#a371f7", opacity: 0.7 + conf * 0.3 },
        width: Math.max(1, conf * 3),
        arrows: { to: { enabled: true, scaleFactor: 0.6 } },
        smooth: { type: "curvedCW", roundness: 0.2 },
        dashes: conf < 0.5,
      };
    }));

    const network = new vis.Network(ref.current, { nodes, edges }, {
      layout: { improvedLayout: true },
      physics: {
        enabled: true,
        barnesHut: { gravitationalConstant: -4000, centralGravity: 0.5, springLength: 120, springConstant: 0.04, damping: 0.09 },
        stabilization: { iterations: 200, updateInterval: 25 },
      },
      interaction: { hover: true, tooltipDelay: 100, zoomView: true, dragView: true },
      edges: { selectionWidth: 2 },
      nodes: { scaling: { min: 10, max: 40 } },
    });
    netRef.current = network;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph]);

  return (
    <div style={{ position: "relative" }}>
      <div ref={ref} style={{ width: "100%", height: 440, border: "1px solid var(--border)", borderRadius: 8, background: "#0d1117" }} />
      <div style={{
        position: "absolute", bottom: 10, right: 10, display: "flex", flexDirection: "column", gap: 4,
        background: "rgba(13,17,23,0.85)", borderRadius: 6, padding: "6px 10px", border: "1px solid var(--border)",
      }}>
        {Object.entries(NODE_COLORS).filter(([k]) => k !== "DEFAULT").map(([type, c]) => (
          <div key={type} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: c.border, flexShrink: 0 }} />
            <span style={{ color: c.font }}>{type}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Final Report ───────────────────────────────────────────────────────────
function Report({ ev }: { ev: Ev }) {
  const report = ev.report as Record<string, unknown> || {};
  const graph = ev.graph as { nodes: unknown[]; edges: unknown[] };
  const flags = (report.flags as Record<string, unknown>[]) || [];
  const facts = (report.key_facts as Record<string, unknown>[]) || [];
  const risk = (report.overall_risk as string) || "CLEAN";
  return (
    <div style={{ padding: "20px 24px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <span style={{ fontSize: 16, fontWeight: 700 }}>Final Report</span>
        <Badge risk={risk} />
        <span style={{ color: "var(--muted)", fontSize: 12 }}>
          {ev.total_facts as number} facts · {ev.total_flags as number} flags · {ev.iterations_run as number} iterations
        </span>
      </div>

      {flags.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)", marginBottom: 10, textTransform: "uppercase", letterSpacing: 1 }}>Risk Flags</div>
          {flags.map((fl, i) => (
            <div key={i} style={{
              display: "flex", gap: 12, padding: "10px 12px", marginBottom: 6,
              background: "var(--surface)", borderRadius: 8, border: "1px solid var(--border)",
              fontSize: 12, alignItems: "flex-start",
            }}>
              <SevBadge sev={fl.severity as string} />
              <div>
                <div style={{ fontWeight: 600, color: "var(--high)", marginBottom: 2 }}>{fl.category as string}</div>
                <div style={{ color: "var(--muted)" }}>{fl.description as string}</div>
                {(fl.sources as string[])?.map((s, j) => (
                  <a key={j} href={s} target="_blank" rel="noreferrer"
                    style={{ fontSize: 11, color: "var(--accent)", display: "block", marginTop: 3 }}>
                    {s.replace("https://", "").slice(0, 70)}
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {graph?.nodes?.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)", marginBottom: 10, textTransform: "uppercase", letterSpacing: 1 }}>
            Identity Graph · {graph.nodes.length} nodes · {graph.edges.length} edges
          </div>
          <Graph graph={graph} />
        </div>
      )}

      {facts.length > 0 && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)", marginBottom: 10, textTransform: "uppercase", letterSpacing: 1 }}>Key Facts ({facts.length})</div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "var(--surface2)" }}>
                  {["Subject", "Relation", "Object", "Conf.", "Source"].map(h => (
                    <th key={h} style={{ padding: "7px 10px", textAlign: "left", color: "var(--muted)", borderBottom: "1px solid var(--border)", fontWeight: 500 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {facts.slice(0, 30).map((f, i) => {
                  const pct = Math.round(((f.confidence as number) || 0) * 100);
                  return (
                    <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}
                      onMouseEnter={e => (e.currentTarget.style.background = "var(--surface)")}
                      onMouseLeave={e => (e.currentTarget.style.background = "transparent")}>
                      <td style={{ padding: "7px 10px", fontWeight: 500 }}>{f.subject as string}</td>
                      <td style={{ padding: "7px 10px", color: "var(--muted)" }}>{f.relation as string}</td>
                      <td style={{ padding: "7px 10px" }}>{f.object as string}</td>
                      <td style={{ padding: "7px 10px", whiteSpace: "nowrap" }}>
                        <span style={{ color: pct >= 90 ? "var(--low)" : pct >= 70 ? "var(--medium)" : "var(--muted)" }}>{pct}%</span>
                      </td>
                      <td style={{ padding: "7px 10px" }}>
                        <a href={f.source as string} target="_blank" rel="noreferrer"
                          style={{ color: "var(--accent)", fontSize: 11 }}>
                          {(f.source as string)?.replace("https://", "").slice(0, 38)}…
                        </a>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Root ───────────────────────────────────────────────────────────────────
export default function Page() {
  const [events, setEvents] = useState<Ev[]>([]);
  const [running, setRunning] = useState(false);
  const [tab, setTab] = useState<"user" | "dev">("user");
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [completeEv, setCompleteEv] = useState<Ev | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadHistory = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/history`);
      if (r.ok) setHistory(await r.json());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  useEffect(() => {
    if (tab === "dev") bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events, tab]);

  const handleRun = useCallback((params: RunParams) => {
    if (running) return;
    if (esRef.current) { esRef.current.close(); esRef.current = null; }

    setEvents([]); setCompleteEv(null); setRunning(true); setTab("user");

    const url = new URL(`${API}/api/stream`);
    url.searchParams.set("target", params.target);
    url.searchParams.set("context", params.context);
    url.searchParams.set("max_iterations", String(params.maxIter));
    url.searchParams.set("researcher_model", params.models.researcher);
    url.searchParams.set("analyst_model", params.models.analyst);
    url.searchParams.set("evaluator_model", params.models.evaluator);

    const es = new EventSource(url.toString());
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data) as Ev;
        setEvents(prev => [...prev, ev]);
        if (ev.event === "complete") {
          setCompleteEv(ev);
          setRunning(false);
          es.close();
          loadHistory();
        }
        if (ev.event === "error") {
          setRunning(false);
          es.close();
        }
      } catch { /* skip malformed */ }
    };

    es.onerror = () => {
      setRunning(false);
      es.close();
    };
  }, [running, loadHistory]);

  const handleReplay = useCallback(async (run_id: string) => {
    try {
      const r = await fetch(`${API}/api/runs/${run_id}`);
      if (!r.ok) return;
      const data = await r.json();
      const evs: Ev[] = data.events || [];
      setEvents(evs);
      setCompleteEv(evs.find(e => e.event === "complete") || null);
      setRunning(false);
    } catch { /* ignore */ }
  }, []);

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", background: "var(--bg)" }}>
      <Sidebar onRun={handleRun} running={running} history={history} onReplay={handleReplay} />

      <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Tab bar */}
        <div style={{
          display: "flex", alignItems: "center",
          borderBottom: "1px solid var(--border)", background: "var(--surface)",
          padding: "0 20px", height: 44, flexShrink: 0,
        }}>
          {(["user", "dev"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: "0 20px", height: "100%", background: "none", border: "none",
              borderBottom: tab === t ? "2px solid var(--accent)" : "2px solid transparent",
              color: tab === t ? "var(--text)" : "var(--muted)",
              fontWeight: tab === t ? 600 : 400, fontSize: 13,
              cursor: "pointer", transition: "color 0.15s",
            }}>
              {t === "user" ? "User View" : "Dev View"}
            </button>
          ))}
          {running && (
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--muted)" }}>
              <Dots /> Investigating...
            </div>
          )}
        </div>

        {/* Content + final report */}
        <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column" }}>
          <div style={{ flex: 1, padding: tab === "user" ? 20 : 0 }}>
            {tab === "user" ? <UserView events={events} /> : <DevView events={events} />}
            <div ref={bottomRef} />
          </div>
          {completeEv && (
            <div style={{ borderTop: "2px solid var(--border)", background: "var(--surface)" }}>
              <Report ev={completeEv} />
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
