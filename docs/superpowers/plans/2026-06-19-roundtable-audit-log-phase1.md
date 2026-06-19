# Roundtable Governance — Phase 1: Audit Log — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. REQUIRED REFERENCE: invoke skills `extending-company-roundtables` and `roundtable-governance-layer` before starting — their Gotchas sections are binding.

**Goal:** Add an append-only `activity_log` to the shared company-roundtable engine, recording who did what and when, exposed via `GET /api/activity` — the foundation every later governance layer writes into.

**Architecture:** One new Postgres table (`activity_log`) auto-created via the existing `SCHEMA_SQL` mechanism in `db.py`. Two new DB helpers: `log_event()` (append-only writer that NEVER raises) and `get_activity()` (reader). A thin `_audit()` wrapper inside `create_company_app()` fires events from the `ask_model` choke point and the decision paths. A new `GET /api/activity` endpoint reads them back. Pure addition — changes no existing roundtable behavior.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, Postgres `ai_mesh` DB. Integration tests via httpx against live containers.

## Global Constraints

- Editing `companies/shared/` changes ALL 5 companies (Holding 8130, MeshTech 8131, MeshMedia 8132, MeshCapital 8133, MeshVentures 8134). Reload = `docker restart`, no rebuild.
- The audit log is **append-only**: never write an UPDATE or DELETE against `activity_log`.
- Audit must **never break a meeting**: `log_event()` swallows all DB errors; audit calls from `ask_model` are fire-and-forget (`asyncio.create_task`) so they add no latency and no failure mode to the roundtable.
- Default psql DB is `templates` — always pass `-d ai_mesh`.
- All schema additions are idempotent (`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`).
- Phase 1 records events only. It does NOT change approval/budget behavior (those are later phases).

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `companies/shared/db.py` | Modify | Append `activity_log` to `SCHEMA_SQL` (ends ~line 181, executed at `db.py:196`); add `log_event()` + `get_activity()`; add `import json` (currently absent). |
| `companies/shared/base_app.py` | Modify | Add `_audit()` wrapper inside `create_company_app()`; call it from `ask_model` (`:180-225`) and decision paths (`:~460/478/902-915`); add `GET /api/activity` endpoint. |
| `tests/test_governance_audit.py` | Create | Integration tests against Holding (`http://localhost:8130`). |

---

### Task 1: `activity_log` table, reader, and `GET /api/activity`

**Files:**
- Modify: `companies/shared/db.py` (SCHEMA_SQL end ~line 181; add `import json` near line 7; add helpers after `get_recent_decisions` ~line 341)
- Modify: `companies/shared/base_app.py` (add endpoint near the other `@app.get` routes, after `/api/decisions` ~line 1022)
- Test: `tests/test_governance_audit.py`

**Interfaces:**
- Produces: `get_activity(company_id: UUID, limit: int = 100, action: Optional[str] = None) -> list[dict]` — rows newest-first. `GET /api/activity?limit=&action=` → `{"company": str, "count": int, "activity": list[dict]}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_governance_audit.py`:

```python
import httpx

HOLDING = "http://localhost:8130"


def test_activity_endpoint_returns_list():
    r = httpx.get(f"{HOLDING}/api/activity", timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["company"] == "holding"
    assert "activity" in body
    assert isinstance(body["activity"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /data/ai-mesh && pytest tests/test_governance_audit.py::test_activity_endpoint_returns_list -v`
Expected: FAIL — `404 Not Found` (endpoint does not exist yet).

- [ ] **Step 3: Add `import json` to `db.py`**

In `companies/shared/db.py`, after `import logging` (line 9), add:

```python
import json
```

- [ ] **Step 4: Append the `activity_log` table to `SCHEMA_SQL`**

In `companies/shared/db.py`, at the END of the `SCHEMA_SQL` string (just before its closing `"""`, ~line 181), add:

```sql

-- Audit log (governance Phase 1) — APPEND-ONLY. Never UPDATE/DELETE.
CREATE TABLE IF NOT EXISTS activity_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    actor_type TEXT NOT NULL,          -- 'model' | 'agent' | 'user' | 'system'
    actor TEXT NOT NULL,               -- model id / participant name / 'system'
    action TEXT NOT NULL,              -- 'model_call' | 'decision_detected' | 'decision_approved' | 'decision_rejected'
    entity_type TEXT,                  -- 'model_call' | 'decision' | 'project'
    entity_id TEXT,
    details JSONB DEFAULT '{}',
    occurred_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_activity_company ON activity_log(company_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_log(company_id, action);
```

- [ ] **Step 5: Add the `get_activity` reader to `db.py`**

In `companies/shared/db.py`, after `get_recent_decisions` (~line 341), add:

```python
async def get_activity(company_id: UUID, limit: int = 100,
                       action: Optional[str] = None) -> list[dict]:
    pool = await get_pool()
    if action:
        rows = await pool.fetch("""
            SELECT * FROM activity_log
            WHERE company_id = $1 AND action = $2
            ORDER BY occurred_at DESC LIMIT $3
        """, company_id, action, limit)
    else:
        rows = await pool.fetch("""
            SELECT * FROM activity_log
            WHERE company_id = $1
            ORDER BY occurred_at DESC LIMIT $2
        """, company_id, limit)
    return [dict(r) for r in rows]
```

- [ ] **Step 6: Add the `GET /api/activity` endpoint to `base_app.py`**

In `companies/shared/base_app.py`, after the `/api/decisions` GET route (~line 1022), add:

```python
    @app.get("/api/activity")
    async def api_activity(limit: int = 100, action: Optional[str] = None):
        """Append-only audit trail for this company (newest first)."""
        if not company_db_id:
            return {"company": COMPANY_CODE, "count": 0, "activity": []}
        from shared.db import get_activity
        rows = await get_activity(company_db_id, limit=limit, action=action)
        for r in rows:
            r["id"] = str(r["id"])
            if r.get("company_id"):
                r["company_id"] = str(r["company_id"])
            if r.get("occurred_at"):
                r["occurred_at"] = r["occurred_at"].isoformat()
        return {"company": COMPANY_CODE, "count": len(rows), "activity": rows}
```

- [ ] **Step 7: Reload the Holding container and confirm the table exists**

Run:
```bash
docker restart ai-mesh-holding-board && sleep 5
docker exec prompt-template-db psql -U admin -d ai_mesh -c "\d activity_log"
```
Expected: table description prints with columns `id, company_id, actor_type, actor, action, entity_type, entity_id, details, occurred_at`.

- [ ] **Step 8: Run the test to verify it passes**

Run: `cd /data/ai-mesh && pytest tests/test_governance_audit.py::test_activity_endpoint_returns_list -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd /data/ai-mesh
git add companies/shared/db.py companies/shared/base_app.py tests/test_governance_audit.py
git commit -m "feat(governance): add append-only activity_log table + GET /api/activity (Phase 1)"
```

---

### Task 2: `_audit()` writer wired into `ask_model` and decision paths

**Files:**
- Modify: `companies/shared/db.py` (add `log_event()` after `get_activity`)
- Modify: `companies/shared/base_app.py` (add `_audit()` helper after the `ask_model` definition ~line 226; call sites in `ask_model` `:211`/`:224` and decision paths `:~460`, `:~478`, `:~904`, `:~914`)
- Test: `tests/test_governance_audit.py`

**Interfaces:**
- Consumes: `get_activity` and the `activity_log` table from Task 1; the module-level `company_db_id` (`base_app.py:125`) and `ask_model` (`:180`).
- Produces: `log_event(company_id, actor_type, actor, action, entity_type=None, entity_id=None, details=None) -> None` (never raises); `_audit(action, actor, actor_type="system", entity_type=None, entity_id=None, **details)` closure.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_governance_audit.py`:

```python
def test_model_call_is_audited():
    # Drive one focused roundtable turn through Holding, then assert it was logged.
    httpx.post(
        f"{HOLDING}/api/execute-task",
        json={"title": "Reply with the single word OK.",
              "description": "One word only.",
              "skill": "strategy",
              "participants": []},   # empty -> engine falls back to first participant
        timeout=180,
    )
    r = httpx.get(f"{HOLDING}/api/activity", params={"action": "model_call", "limit": 5}, timeout=30)
    assert r.status_code == 200
    events = r.json()["activity"]
    assert len(events) >= 1, "expected at least one model_call audit event"
    assert events[0]["action"] == "model_call"
    assert events[0]["actor_type"] == "model"
    assert "latency_ms" in events[0]["details"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /data/ai-mesh && pytest tests/test_governance_audit.py::test_model_call_is_audited -v`
Expected: FAIL — `assert len(events) >= 1` fails (no writer wired yet; activity is empty for `model_call`).

- [ ] **Step 3: Add the `log_event` writer to `db.py`**

In `companies/shared/db.py`, after `get_activity` (from Task 1), add:

```python
async def log_event(company_id: UUID, actor_type: str, actor: str, action: str,
                    entity_type: Optional[str] = None, entity_id: Optional[str] = None,
                    details: Optional[dict] = None) -> None:
    """Append-only audit write. NEVER raises — audit failure must not break a meeting."""
    try:
        pool = await get_pool()
        await pool.execute("""
            INSERT INTO activity_log
                (company_id, actor_type, actor, action, entity_type, entity_id, details)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        """, company_id, actor_type, actor, action, entity_type, entity_id,
             json.dumps(details or {}))
    except Exception as e:
        logger.warning(f"audit log_event failed ({action}): {e}")
```

- [ ] **Step 4: Add the `_audit()` helper to `base_app.py`**

In `companies/shared/base_app.py`, immediately AFTER the `ask_model` function ends (~line 226, before `build_messages`), add:

```python
    async def _audit(action: str, actor: str, actor_type: str = "system",
                     entity_type: Optional[str] = None, entity_id: Optional[str] = None,
                     **details) -> None:
        """Fire-and-forget audit. No-op if DB not initialized; log_event swallows errors."""
        if not company_db_id:
            return
        from shared.db import log_event
        await log_event(company_db_id, actor_type, actor, action,
                        entity_type, entity_id, details or None)
```

- [ ] **Step 5: Wire `model_call` into `ask_model` (success path)**

In `companies/shared/base_app.py`, in `ask_model`, between `update_stats(model_id, True, elapsed_ms)` (line 211) and `return data["choices"][0]["message"]["content"]` (line 212), insert:

```python
                usage = data.get("usage") or {}
                asyncio.create_task(_audit(
                    "model_call", actor=model_name, actor_type="model",
                    entity_type="model_call", success=True,
                    latency_ms=round(elapsed_ms),
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    total_tokens=usage.get("total_tokens")))
```

- [ ] **Step 6: Wire `model_call` into `ask_model` (failure path)**

In `companies/shared/base_app.py`, in `ask_model`, between `update_stats(model_id, False, elapsed_ms, "error", last_error)` (line 224) and `return last_error` (line 225), insert:

```python
        asyncio.create_task(_audit(
            "model_call", actor=model_name, actor_type="model",
            entity_type="model_call", success=False,
            latency_ms=round(elapsed_ms), error=last_error[:200]))
```

- [ ] **Step 7: Wire decision events into the decision paths**

In `companies/shared/base_app.py`:

(a) In `detect_and_execute_decisions`, after EACH `pending_decisions[decision_id] = {...}` assignment (~line 460 and ~line 478), add on the next line (same indentation):

```python
                await _audit("decision_detected", actor="Synthesizer", actor_type="system",
                             entity_type="decision", entity_id=decision_id,
                             description=description)
```

(b) In the WebSocket `approve_decision` / `reject_decision` handler (~line 904–914), after the status is set to `"executing"` add:

```python
                        await _audit("decision_approved", actor="CEO", actor_type="agent",
                                     entity_type="decision", entity_id=did)
```

and after the status is set to `"rejected"` (line ~914) add:

```python
                        await _audit("decision_rejected", actor="CEO", actor_type="agent",
                                     entity_type="decision", entity_id=did)
```

- [ ] **Step 8: Reload and run the test to verify it passes**

Run:
```bash
docker restart ai-mesh-holding-board && sleep 5
cd /data/ai-mesh && pytest tests/test_governance_audit.py::test_model_call_is_audited -v
```
Expected: PASS — at least one `model_call` event with `latency_ms` in `details`.

- [ ] **Step 9: Manually verify decision events (non-deterministic trigger)**

Decision events fire only when synthesis emits an `[ACTION:…]` tag, which is model-dependent and not asserted in a gated test. Verify the plumbing directly:
```bash
docker exec prompt-template-db psql -U admin -d ai_mesh \
  -c "SELECT action, actor, actor_type, count(*) FROM activity_log GROUP BY 1,2,3 ORDER BY 1;"
```
Expected: `model_call` rows present. After a pitch that produces an action, `decision_detected` rows appear too.

- [ ] **Step 10: Roll out to the other four companies and run the full suite**

```bash
docker restart ai-mesh-meshtech ai-mesh-meshmedia ai-mesh-meshcapital ai-mesh-meshventures && sleep 5
cd /data/ai-mesh && pytest tests/test_governance_audit.py -v
```
Expected: both tests PASS. (Engine is shared; the restart just reloads the same code in each container.)

- [ ] **Step 11: Commit**

```bash
cd /data/ai-mesh
git add companies/shared/db.py companies/shared/base_app.py tests/test_governance_audit.py
git commit -m "feat(governance): record model_call + decision events to activity_log (Phase 1)"
```

---

## Self-Review

**Spec coverage (vs `roundtable-governance-layer` Phase 1):**
- "New `activity_log` table + `log_event(...)` helper" → Task 1 Step 4, Task 2 Step 3. ✓
- "Immutable, append-only" → Global Constraints + schema comment; no UPDATE/DELETE anywhere. ✓
- "Wire into `ask_model` (call + cost)" → Task 2 Steps 5–6; `usage` captured now (cost computation is Phase 3, but tokens are already logged). ✓
- "decision flow" → Task 2 Step 7. ✓
- "Add `GET /api/activity`" → Task 1 Step 6. ✓
- "Independently shippable — pure addition, no behavior change" → no existing code path altered; only additive inserts and a new route. ✓

**Gotcha coverage:**
- Append-only → enforced by omission + explicit constraint. ✓
- Audit must not break a meeting → `log_event` try/except + fire-and-forget `create_task` in `ask_model`. ✓
- `ask_model` drops `usage` → now captured in Step 5. ✓
- Editing `shared/` hits all 5 → Step 10 rolls out + tests. ✓
- Restart-to-reload → every verification restarts before testing. ✓

**Placeholder scan:** none — every code step shows complete code; every run step shows command + expected output.

**Type consistency:** `get_activity` / `log_event` signatures match between db.py definitions (Task 1 Step 5, Task 2 Step 3) and call sites (`_audit`, endpoint). `company_db_id` (UUID) is the company-scope key throughout. `details` is always a dict, serialized via `json.dumps(...)::jsonb`. ✓

**Note on line numbers:** all `:NNN` references are from the audited state on 2026-06-19. If earlier edits shift them, locate by the quoted anchor lines (e.g. `update_stats(model_id, True, elapsed_ms)`), not the raw number.
