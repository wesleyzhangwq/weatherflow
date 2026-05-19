# Dev Review History and Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact Dev Review history surface across backend, CLI, and dashboard.

**Architecture:** Reuse existing `dev_reviews` and `agent_runs` persistence. Add a repository list helper, expose it through a bounded FastAPI endpoint, then consume the same list from the CLI and dashboard.

**Tech Stack:** FastAPI, Pydantic models, SQLite repository helpers, Typer CLI, Next.js/TypeScript.

---

## Task 1: Backend History Endpoint

**Files:**
- Modify: `backend/app/memory/dev_review_repo.py`
- Modify: `backend/app/routers/dev_review.py`
- Test: `backend/tests/test_dev_review_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests that create two persisted reviews, call `GET /api/dev-review/runs`, and assert newest-first ordering and limit behavior.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
cd backend && UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_dev_review_api.py -q
```

Expected: failure because the route does not exist.

- [ ] **Step 3: Implement repository list helper**

Add `list_reviews(limit: int = 5) -> list[DevReviewRecord]` to `dev_review_repo.py`, ordered by `created_at DESC, id DESC`.

- [ ] **Step 4: Implement route**

Add:

```python
@router.get("/runs", response_model=list[DevReviewRecord])
def dev_review_runs(limit: int = Query(default=5, ge=1, le=20)) -> list[DevReviewRecord]:
    return dev_review_repo.list_reviews(limit=limit)
```

- [ ] **Step 5: Run focused tests and commit**

Run the focused backend tests. Commit with:

```bash
git commit -m "feat: add dev review run history api"
```

## Task 2: CLI History

**Files:**
- Modify: `cli/weatherflow_cli/dev_review.py`

- [ ] **Step 1: Add CLI option**

Add `--history` to `wf dev-review`.

- [ ] **Step 2: Add deterministic history formatter**

Add `_print_history(items)` and `_coverage_summary(coverage)` helpers.

- [ ] **Step 3: Verify CLI help**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --package weatherflow-cli wf dev-review --help
```

Expected: `--history` appears.

- [ ] **Step 4: Run lint and commit**

Run ruff on CLI files and commit:

```bash
git commit -m "feat: add dev review history cli"
```

## Task 3: Dashboard History

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/components/DevReviewPanel.tsx`

- [ ] **Step 1: Add API client method**

Add `devReviewHistory(limit = 5)`.

- [ ] **Step 2: Fetch history on dashboard**

Fetch `/api/dev-review/runs?limit=5` in `frontend/app/page.tsx` and pass it into `DevReviewPanel`.

- [ ] **Step 3: Render compact history**

Add a small history list below the current review details. Each row shows created time, weather, run status, and provider coverage summary.

- [ ] **Step 4: Run frontend lint/build and commit**

Run:

```bash
cd frontend && npm run lint && npm run build
```

Commit:

```bash
git commit -m "feat: show dev review history"
```

## Task 4: Final Verification

**Files:**
- No new files expected.

- [ ] **Step 1: Run full check**

Run:

```bash
make check
```

- [ ] **Step 2: Check git status**

Run:

```bash
git status --short
```

- [ ] **Step 3: Summarize result**

Report commits, verification evidence, and remaining product gaps.
