# Provider Readiness UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pre-run provider readiness visibility for the Dev Review Agent in the backend API, CLI, and dashboard panel.

**Architecture:** Keep readiness local and deterministic: it checks required environment values only and does not call remote provider APIs. The backend exposes `/api/dev-review/providers`; CLI and frontend consume that endpoint to explain whether Dev Review can run before the user triggers a run.

**Tech Stack:** FastAPI, Pydantic, Typer, Next.js App Router, TypeScript, existing WeatherFlow API helpers.

---

## File Map

- Modify `backend/app/memory/schemas.py`: add readiness status/model.
- Modify `backend/app/routers/dev_review.py`: add provider readiness helper and endpoint.
- Modify `backend/tests/test_dev_review_api.py`: add readiness endpoint tests.
- Modify `cli/weatherflow_cli/dev_review.py`: add `--check`.
- Modify `frontend/lib/api.ts`: add provider readiness types/helper.
- Modify `frontend/components/DevReviewPanel.tsx`: show readiness and disable Run only when known zero-ready.
- Modify `frontend/app/page.tsx`: fetch readiness and pass it to the panel.

## Task 1: Backend Readiness Endpoint

**Files:**
- Modify: `backend/app/memory/schemas.py`
- Modify: `backend/app/routers/dev_review.py`
- Modify: `backend/tests/test_dev_review_api.py`

- [ ] **Step 1: Write failing backend tests**

Append to `backend/tests/test_dev_review_api.py`:

```python
def test_dev_review_providers_need_config_when_env_missing(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    client = _client()
    response = client.get("/api/dev-review/providers")

    assert response.status_code == 200
    providers = {item["name"]: item for item in response.json()}
    assert providers["github"]["status"] == "needs_config"
    assert providers["github"]["required_env"] == "GITHUB_TOKEN"
    assert providers["google_calendar"]["status"] == "needs_config"
    assert providers["google_calendar"]["required_env"] == "GOOGLE_CALENDAR_ACCESS_TOKEN"
    assert providers["github"]["blocking"] is False
    assert providers["google_calendar"]["blocking"] is False


def test_dev_review_providers_reports_each_ready_env(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    client = _client()
    response = client.get("/api/dev-review/providers")

    assert response.status_code == 200
    providers = {item["name"]: item for item in response.json()}
    assert providers["github"]["status"] == "ready"
    assert providers["google_calendar"]["status"] == "needs_config"

    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "calendar-token")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    response = client.get("/api/dev-review/providers")

    assert response.status_code == 200
    providers = {item["name"]: item for item in response.json()}
    assert providers["github"]["status"] == "needs_config"
    assert providers["google_calendar"]["status"] == "ready"


def test_dev_review_providers_reports_both_ready(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "calendar-token")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    client = _client()
    response = client.get("/api/dev-review/providers")

    assert response.status_code == 200
    providers = {item["name"]: item for item in response.json()}
    assert providers["github"]["status"] == "ready"
    assert providers["google_calendar"]["status"] == "ready"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend && UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_dev_review_api.py -k providers -v
```

Expected: FAIL because `/api/dev-review/providers` does not exist.

- [ ] **Step 3: Add schemas**

In `backend/app/memory/schemas.py`, add near the Dev Review models:

```python
DevReviewProviderReadinessStatus = Literal["ready", "needs_config"]


class DevReviewProviderReadiness(BaseModel):
    name: Literal["github", "google_calendar"]
    label: str
    status: DevReviewProviderReadinessStatus
    required_env: str
    used_for: str
    blocking: bool = False
```

Add both names to `__all__`.

- [ ] **Step 4: Add endpoint**

In `backend/app/routers/dev_review.py`, import `DevReviewProviderReadiness` and add:

```python
@router.get("/providers", response_model=list[DevReviewProviderReadiness])
def dev_review_providers() -> list[DevReviewProviderReadiness]:
    settings = get_settings()
    return [
        DevReviewProviderReadiness(
            name="github",
            label="GitHub",
            status="ready" if settings.github_token.strip() else "needs_config",
            required_env="GITHUB_TOKEN",
            used_for="PRs, issues, reviews, repository activity",
            blocking=False,
        ),
        DevReviewProviderReadiness(
            name="google_calendar",
            label="Google Calendar",
            status=(
                "ready"
                if settings.google_calendar_access_token.strip()
                else "needs_config"
            ),
            required_env="GOOGLE_CALENDAR_ACCESS_TOKEN",
            used_for="meeting load, focus windows, calendar event titles",
            blocking=False,
        ),
    ]
```

- [ ] **Step 5: Run backend readiness tests**

Run:

```bash
cd backend && UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_dev_review_api.py -k providers -v
```

Expected: PASS.

- [ ] **Step 6: Run focused backend API tests**

Run:

```bash
cd backend && UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_dev_review_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit backend endpoint**

```bash
git add backend/app/memory/schemas.py backend/app/routers/dev_review.py backend/tests/test_dev_review_api.py
git commit -m "feat: expose dev review provider readiness"
```

## Task 2: CLI `--check`

**Files:**
- Modify: `cli/weatherflow_cli/dev_review.py`

- [ ] **Step 1: Update CLI function signature**

In `cli/weatherflow_cli/dev_review.py`, add a `check` option:

```python
check: bool = typer.Option(
    False,
    "--check",
    help="Show Dev Review provider readiness without running a review.",
),
```

- [ ] **Step 2: Implement check branch**

At the start of `run`, before `latest`, add:

```python
        if check:
            data = api.get("/api/dev-review/providers")
            _print_provider_check(data)
            return
```

Add:

```python
def _print_provider_check(items: list[dict[str, Any]]) -> None:
    typer.echo("Dev Review Providers")
    if not items:
        typer.echo("-")
        return
    for item in items:
        typer.echo(
            f"- {_text(item.get('label') or item.get('name'))}: "
            f"{_text(item.get('status'))} ({_text(item.get('required_env'))})"
        )
```

- [ ] **Step 3: Verify CLI help**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run wf dev-review --help
```

Expected: help includes `--check`.

- [ ] **Step 4: Run CLI lint**

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --package weatherflow-backend --extra dev ruff check cli/weatherflow_cli
```

Expected: PASS.

- [ ] **Step 5: Commit CLI check**

```bash
git add cli/weatherflow_cli/dev_review.py
git commit -m "feat: add dev review provider check cli"
```

## Task 3: Frontend Readiness UI

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/components/DevReviewPanel.tsx`
- Modify: `frontend/app/page.tsx`

- [ ] **Step 1: Add frontend types and API helper**

In `frontend/lib/api.ts`, add:

```ts
export type DevReviewProviderReadinessStatus = "ready" | "needs_config";

export interface DevReviewProviderReadiness {
  name: "github" | "google_calendar";
  label: string;
  status: DevReviewProviderReadinessStatus;
  required_env: string;
  used_for: string;
  blocking: boolean;
}
```

Add helper to `api`:

```ts
  devReviewProviders: () =>
    request<DevReviewProviderReadiness[]>("/api/dev-review/providers"),
```

- [ ] **Step 2: Update panel props and state**

In `frontend/components/DevReviewPanel.tsx`, import the type and change props:

```tsx
export function DevReviewPanel({
  initial,
  providers
}: {
  initial: DevReview | null;
  providers: DevReviewProviderReadiness[];
}) {
```

Add:

```tsx
  const readinessKnown = providers.length > 0;
  const readyCount = providers.filter((item) => item.status === "ready").length;
  const canRun = !readinessKnown || readyCount > 0;
```

- [ ] **Step 3: Render provider readiness**

Inside the panel before the summary paragraph, add a compact section:

```tsx
      <div className="mt-4 flex flex-wrap gap-2">
        {providers.length ? (
          providers.map((provider) => (
            <span
              key={provider.name}
              className="rounded-full border border-black/10 px-3 py-1 text-xs dark:border-white/10"
              title={provider.used_for}
            >
              {provider.label}: {provider.status === "ready" ? "Ready" : "Needs config"}
            </span>
          ))
        ) : (
          <span className="text-xs muted">Provider readiness unavailable.</span>
        )}
      </div>
```

- [ ] **Step 4: Disable Run only for known zero-ready**

Change button disabled to:

```tsx
disabled={running || !canRun}
```

Change empty-state text to:

```tsx
        {review?.summary ||
          (canRun
            ? "Run a dev review to turn recent work and calendar signals into one development rhythm snapshot."
            : "Configure GitHub or Google Calendar before running a Dev Review.")}
```

Optionally add concise setup guidance when `!canRun`:

```tsx
      {!canRun ? (
        <p className="mt-2 text-xs muted">
          Set GITHUB_TOKEN or GOOGLE_CALENDAR_ACCESS_TOKEN in your environment.
        </p>
      ) : null}
```

- [ ] **Step 5: Fetch providers on home page**

In `frontend/app/page.tsx`, import `DevReviewProviderReadiness` type and fetch:

```tsx
      fetchOk<DevReviewProviderReadiness[]>("/api/dev-review/providers")
```

Update destructuring and render:

```tsx
        <DevReviewPanel initial={devReview} providers={devReviewProviders ?? []} />
```

- [ ] **Step 6: Run frontend checks**

Run:

```bash
cd frontend && npm run lint
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 7: Commit frontend readiness UI**

```bash
git add frontend/lib/api.ts frontend/components/DevReviewPanel.tsx frontend/app/page.tsx
git commit -m "feat: show dev review provider readiness"
```

## Task 4: Final Verification

**Files:**
- No planned source edits unless verification reveals a bug.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
cd backend && UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_dev_review_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full project check**

Run:

```bash
make check
```

Expected: PASS.

- [ ] **Step 3: Verify git status**

Run:

```bash
git status --short
```

Expected: no output.

## Self-Review Notes

- Spec coverage: backend readiness endpoint, CLI `--check`, frontend readiness display, disabled-run behavior, and tests are covered.
- Scope check: no OAuth, no remote health checks, no new providers, no dashboard redesign.
- Type consistency: `DevReviewProviderReadiness` naming is shared across backend and frontend.
