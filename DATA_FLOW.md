# Data Flow & Architecture Guide

## Overview

The Fraud Agent has **three-layer data persistence**:

1. **Local JSON** (ALWAYS saved) - `outputs/runs/{run_id}.json`
2. **MongoDB Atlas** (Optional) - Full run data + events
3. **Neo4j Aura** (Optional) - Identity graph

This provides **redundancy**: app works fully offline with just JSON, but leverages databases when available.

---

## WRITE Flow (During Investigation)

### 1. Real-time Streaming (Port 8000)
**URL**: `GET /api/stream?target=...&context=...&max_iterations=...`

- Browser connects via native `EventSource` API
- Backend launches LLM agents in ThreadPoolExecutor
- Each agent emits events via callback function
- Events are queued in-memory and streamed as SSE (Server-Sent Events)
- No database writes during streaming (real-time performance)

### 2. After Investigation Completes
When all agents finish, the `finally` block in `server.py:_run()` executes:

```python
# STEP 1: Save to Local JSON (ALWAYS)
outputs/runs/{run_id}.json
├── run_id: unique identifier
├── request: {target, context}
└── events: [all 100+ events from investigation]

# STEP 2: Save to MongoDB (if configured)
- Collection: fraud_agent.runs
- Document:
  ├── run_id
  ├── target
  ├── context
  ├── overall_risk
  ├── total_facts
  ├── total_flags
  ├── iterations
  ├── report (final summary)
  ├── graph (nodes/edges)
  ├── events (all events)
  └── created_at (timestamp)

# STEP 3: Save to Neo4j (if configured)
- Nodes: People, Organizations, Entities
- Edges: Relationships from facts
- Flags: Risk flags linked to target
- Indexed by run_id for cleanup
```

---

## READ Flow (Via API)

### /api/history (Get all past runs)
```
GET /api/history
├── Try MongoDB first → mongo_get_history(50)
│   └── Returns: [{run_id, target, context, overall_risk, total_facts, total_flags, ts}, ...]
└── Fallback → Local JSON files sorted by mtime
    └── Reads outputs/runs/*.json → extracts summary
```

**Why two sources?**
- MongoDB is faster for large result sets
- JSON files work when DB is down or unconfigured
- Frontend gets data either way

### /api/runs/{run_id} (Get specific run)
```
GET /api/runs/c8cc9100
├── Try MongoDB first → mongo_get_run(run_id)
│   └── Returns: {full run data with events, graph, report}
└── Fallback → outputs/runs/{run_id}.json
    └── Returns: {run data}
```

### /api/db-status (Check DB health)
```
GET /api/db-status
└── Returns: {mongodb: true/false, neo4j: true/false}
```

---

## Frontend Integration

### 1. Real-time Investigation (page.tsx)
```tsx
const es = new EventSource(
  `/api/stream?target=...&context=...&max_iterations=...`
)
es.onmessage = (e) => {
  const event = JSON.parse(e.data)
  setEvents(prev => [...prev, event])  // Stream to UI
  if (event.event === "complete") {
    loadHistory()  // Refresh sidebar
    setCompleteEv(event)  // Show final report + graph
  }
}
```

**Data source**: Real-time stream (no DB involved)

### 2. History Sidebar
```tsx
// Fetch past runs
fetch(`/api/history`)
  .then(r => r.json())
  .then(history => setHistory(history))  // Show list
```

**Data source**: MongoDB (preferred) → JSON files (fallback)

### 3. Replay Run
```tsx
// When user clicks history item
fetch(`/api/runs/{run_id}`)
  .then(r => r.json())
  .then(data => {
    setEvents(data.events)  // Display all events
    setCompleteEv(complete_event)  // Show report
  })
```

**Data source**: MongoDB (preferred) → JSON file (fallback)

### 4. Identity Graph Visualization
```tsx
// In Report component
<Graph graph={completeEv.graph} />
// graph = {nodes: [...], edges: [...]}
// Rendered with vis-network (CDN)
```

**Data source**: 
- During streaming: from `complete` event (built from facts)
- On replay: from stored report in MongoDB/JSON

---

## Database Configuration

### MongoDB Atlas (Optional)
**Status**: Currently **CONNECTED ✓**

```env
MONGODB_URI=mongodb+srv://harshithh2025:HnEigIaG0TCKbBB7@cluster0.kqvfzw9.mongodb.net
```

**What gets saved**:
- Full run metadata
- All events (every agent log, query, fact, flag)
- Final report (summary, flags, key facts)
- Graph (nodes, edges)
- Timestamp for sorting

**Benefits**:
- Query runs by target, risk level, date range
- Persist investigation history long-term
- Fast history/replay on fresh frontend visits

**Fallback**: If DB down or unconfigured → reads from `outputs/runs/*.json`

### Neo4j Aura (Optional)
**Status**: Currently **NOT CONNECTED** (placeholder URI)

```env
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io  # <- Placeholder
NEO4J_USER=ae37ec4d
NEO4J_PASS=u2guBRGfJhIlJPiWlaQcJAX5BdUmZsMIYoUCHtky7Qc
```

**To enable Neo4j**:
1. Go to https://neo4j.com/cloud/aura/
2. Sign in with Google → Create Free instance
3. Copy the connection URI (NOT placeholder)
4. Update `.env` with real URI
5. Restart server

**What gets saved**:
- Person/Organization/Entity nodes
- CONNECTED relationships (from facts)
- HAS_FLAG relationships (risk flags)
- All indexed by run_id

**Benefits**:
- Visual graph queries ("Who's connected to Timothy?")
- Relationship patterns across runs
- Graph analytics

**Fallback**: If Neo4j unconfigured or fails → graph still shows from in-memory report

---

## Key Points

### 1. **Local JSON is ALWAYS saved**
- Provides complete redundancy
- No external dependencies
- Works offline
- Can be imported into any system

### 2. **MongoDB + Neo4j are OPTIONAL**
- App functions 100% without them
- Can be added/removed at any time
- Credentials in `.env` (safe to leave blank)
- Graceful fallback to JSON

### 3. **Data integrity**
- Events streamed in real-time (no loss)
- Complete event log preserved
- Graph reconstructed on demand (not lossy)
- Retry logic for network failures (3 attempts, 30s gap)

### 4. **Timeline of a run**
```
1. User clicks "Run Investigation"
   ↓
2. Backend launches 3 agents (researcher → analyst → evaluator)
   ↓
3. Each agent emits events real-time
   ↓
4. Frontend streams events via EventSource
   ↓
5. Investigation completes
   ↓
6. Backend FINALLY block:
   - Save to local JSON (ALWAYS)
   - Save to MongoDB (if configured)
   - Save graph to Neo4j (if configured)
   ↓
7. Frontend receives "complete" event
   - Displays final report + graph
   - Loads updated history
   - Enables replay for this run
   ↓
8. History sidebar shows new run
   - Fetches from /api/history (MongoDB → JSON)
   - User can click to replay
```

---

## Testing Data Flow

**Run test script**:
```bash
cd fraud_agent
source venv/Scripts/activate
python test_simple.py
```

**Expected output**:
- ✓ DB Status: mongodb=true (or false)
- ✓ Investigation completes
- ✓ Local JSON saved
- ✓ MongoDB saved (if enabled)
- ✓ Neo4j graph saved (if enabled)
- ✓ History endpoint works
- ✓ Run endpoint works

---

## Troubleshooting

### "Run completed but not in MongoDB history"
1. Check `/api/db-status` returns `mongodb: true`
2. Check `MONGODB_URI` in `.env` is valid
3. Check MongoDB Atlas cluster is running
4. Look at server logs for mongo_save_run() errors

### "No local JSON files"
1. Check `outputs/runs/` directory exists
2. Check write permissions on that folder
3. Look at server logs for write errors

### "Graph not showing"
1. Neo4j optional - graph still shows from in-memory report
2. If you want persistent Neo4j:
   - Set up Neo4j Aura (free account)
   - Update NEO4J_URI in .env
   - Restart server
3. Check `/api/db-status` returns neo4j status

### "Frontend history empty"
1. Check `/api/history` endpoint responds
2. Check at least one run has completed
3. Check browser console for fetch errors
4. Try `/api/db-status` to see DB connections

---

## Summary

```
WRITE:  SSE stream → (investigation completes) → Local JSON + MongoDB + Neo4j
READ:   /api/history → [MongoDB first, JSON fallback]
        /api/runs/{id} → [MongoDB first, JSON fallback]
FRONTEND: EventSource stream → Report + Graph
          History sidebar → /api/history
          Replay → /api/runs/{id}
```

**The key design**: 
- Real-time streaming for UX (no latency)
- Background persistence (after completion)
- Optional databases for advanced queries
- JSON fallback for reliability
