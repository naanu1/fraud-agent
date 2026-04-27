# How to Enable Neo4j Graph Database (5-10 minutes)

## Why Neo4j?

MongoDB stores **records** (investigations). Neo4j stores **relationships** (who's connected to whom).

For a fraud investigation system:
- **MongoDB**: "Give me all investigations of Timothy Overturf"
- **Neo4j**: "Show me everyone connected to Timothy Overturf across all investigations"

---

## Step-by-Step Setup

### Step 1: Create Free Neo4j Aura Account (2 minutes)

1. Go to: https://neo4j.com/cloud/aura/
2. Click "Create a free instance"
3. Sign in with **Google** or **GitHub** (no credit card!)
4. Wait for instance to be created (1-2 minutes)

### Step 2: Get Connection Details (1 minute)

Once instance is created:
1. Click on your instance
2. Click "Copy" on the Connection URI
   - Looks like: `neo4j+s://xxxxxxxx.databases.neo4j.io`
3. Note the **password** shown (or generate new one if needed)
   - Username is always: `neo4j`

### Step 3: Update .env File (1 minute)

Edit `.env` in the fraud_agent folder:

```bash
# BEFORE (broken - placeholder):
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
NEO4J_USER=ae37ec4d
NEO4J_PASS=u2guBRGfJhIlJPiWlaQcJAX5BdUmZsMIYoUCHtky7Qc

# AFTER (from Neo4j Aura):
NEO4J_URI=neo4j+s://aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASS=your-generated-password-from-neo4j-aura
```

### Step 4: Restart Server (1 minute)

In PowerShell:
```powershell
cd "c:\Users\Harshith M\Documents\New folder\fraud_agent"
& "venv\Scripts\Activate.ps1"
# Stop previous server (Ctrl+C or kill it)
uvicorn server:app --host 0.0.0.0 --port 8000 --log-level warning
```

### Step 5: Verify Connection (1 minute)

Test the connection:
```bash
curl http://localhost:8000/api/db-status
```

Expected response:
```json
{"mongodb": true, "neo4j": true}
```

If Neo4j shows `false`:
- Check `.env` has correct URI (no placeholders)
- Check password is correct
- Check Neo4j Aura instance is running
- Restart server

---

## What Happens After?

### First Run After Enabling Neo4j

When you run an investigation:

```
1. Research → Analyst → Evaluator (as normal)
   ↓
2. Backend saves data:
   - Local JSON ✓ (always)
   - MongoDB ✓ (always)
   - Neo4j ✓ (NOW WORKING!)
       ├─ Creates 8 nodes (people, organizations, entities)
       ├─ Creates 7 edges (relationships)
       └─ Indexes by run_id (for cleanup)
   ↓
3. Frontend shows graph visualization
```

### Example: Timothy Overturf

**Neo4j will store**:
- Nodes:
  - Timothy Overturf (PERSON)
  - Sisu Capital, LLC (ORGANIZATION)
  - Hans Overturf (PERSON)
  - SEC (ORGANIZATION)
  - Arcata, California (LOCATION)

- Edges:
  - Timothy → owner of → Sisu Capital
  - Timothy → resident of → Arcata
  - Hans → father of → Timothy
  - Timothy → violated → Investment Advisers Act
  - SEC → charged → Timothy

### Querying Neo4j

Once data is saved, you can query it via Neo4j Browser:

```cypher
# Who's connected to Timothy Overturf?
MATCH (t:Entity {name: 'Timothy Overturf'})-[r]->(other)
RETURN t, r, other

# Show all relationships
MATCH (a)-[r]->(b)
WHERE a.run_id = 'c8cc9100'
RETURN a, r, b

# Find patterns across runs
MATCH (n {run_id: 'c8cc9100'})-[r]-(m)
RETURN count(*) as total_relationships
```

---

## Troubleshooting

### Neo4j still shows as `false` after restart

**Check 1**: Correct URI format
```
Good: neo4j+s://xxxxxxxx.databases.neo4j.io
Bad:  neo4j+s://xxxxxxxx.databases.neo4j.io  <- extra characters
Bad:  xxxxxxxx.databases.neo4j.io  <- missing neo4j+s://
```

**Check 2**: Neo4j Aura instance is active
- Go to https://neo4j.com/cloud/aura/
- Check instance shows "Running" (green)
- If stopped, click "Resume"

**Check 3**: Credentials are correct
```env
# Must be from Neo4j Aura, not from config
NEO4J_USER=neo4j  # Always this
NEO4J_PASS=xyz   # From Neo4j Aura setup
```

**Check 4**: Server logs for connection errors
```bash
# If running locally, check for error messages
# If remote, check server logs
```

### Data not showing in Neo4j Browser

1. Go to https://neo4j.com/cloud/aura/
2. Click your instance → "Open"
3. Run a query:
   ```cypher
   MATCH (n) RETURN n LIMIT 10
   ```
4. If no results, data hasn't been saved yet
   - Run an investigation
   - Check server logs for neo4j_save_graph() calls

### MongoDB working but Neo4j isn't

This is fine! System still works:
- Local JSON saves ✓
- MongoDB saves ✓
- Neo4j saves will fail silently (logged as warning)
- Graph still displays (from in-memory report)

To fix: Follow troubleshooting steps above.

---

## Free Neo4j Limits

| Limit | Amount |
|-------|--------|
| Storage | 100 KB (plenty for graphs with <1000 nodes) |
| Monthly | No limit |
| Concurrent connections | 2 |
| Node/relationship creation | Unlimited |

For a fraud investigation system with <100 runs, this is more than enough.

---

## Optional: Query Your Graph

Once Neo4j is enabled and you've run investigations:

```bash
# Access Neo4j Browser
# https://neo4j.com/cloud/aura/ → Click instance → "Open"

# View all data
MATCH (n) RETURN n

# Find connections to target
MATCH (t:Entity {name: 'Timothy Overturf'})-[r]-(other)
RETURN t, r, other

# Show confidence scores
MATCH (a)-[r:CONNECTED]->(b)
RETURN a.name, r.relation, b.name, r.confidence
ORDER BY r.confidence DESC

# Find high-confidence relationships
MATCH (a)-[r:CONNECTED {run_id: 'c8cc9100'}]->(b)
WHERE r.confidence >= 0.90
RETURN a, r, b

# List all risk flags
MATCH (f:Flag)-[:HAS_FLAG]-(target)
RETURN target.name, f.category, f.severity, f.description
```

---

## Summary

- ✓ Neo4j is free (Google/GitHub login, no credit card)
- ✓ Takes 5 minutes to set up
- ✓ Complements MongoDB (not replaces)
- ✓ Enables relationship analysis across investigations
- ✓ Graph browser for visual queries

**After setup**: All future investigations automatically save to Neo4j. Past investigations stay in local JSON + MongoDB.
