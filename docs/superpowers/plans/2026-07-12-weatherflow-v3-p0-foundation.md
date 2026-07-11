# WeatherFlow v3 P0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Archive the final v2 baseline, remove every v2 runtime surface, switch repository authority to v3, and leave a clean, tested Python 3.12 daemon skeleton that later P1 work can extend.

**Architecture:** P0 creates one `uv` workspace member, `core/`, using a `src/weatherflow` package. The only runtime behavior is a typed FastAPI health endpoint and a small `weatherflow serve` CLI; this is intentionally thin. Repository contracts prevent v2 directories or authority docs from reappearing, while `weatherflow-architecture-v3.md` and the approved design specification become the normative design set.

**Tech Stack:** Python 3.12, uv workspace, FastAPI, Pydantic Settings, Uvicorn, pytest, pytest-asyncio, HTTPX TestClient, Ruff, GitHub Actions.

---

## Scope and execution rules

- Execute this plan in an isolated worktree created with `superpowers:using-git-worktrees`.
- Recommended branch: `codex/weatherflow-v3-p0-foundation`.
- Do not push the `weatherflow-v2-final` tag or the branch without explicit user instruction.
- Do not copy implementation code from v2 into `core/`.
- Preserve only:
  - Git history and the local `weatherflow-v2-final` tag;
  - `.gitignore`, `.gitleaksignore`, and GitHub repository metadata that is still valid;
  - the approved v3 design and implementation plans under `docs/superpowers/`.
- Remove v2 runtime code, v2 product docs, v2 assets, the Electron prototype, old MCP/Skills implementations, and old lock/config files.
- Use TDD for repository contracts, API behavior, configuration, and CLI behavior.
- Each commit must contain only the files listed in its task.

## Locked file structure after P0

```text
WeatherFlow/
├── .env.example
├── .github/workflows/ci.yml
├── .gitignore
├── .gitleaksignore
├── AGENTS.md
├── Makefile
├── README.md
├── pyproject.toml
├── uv.lock
├── weatherflow-architecture-v3.md
├── core/
│   ├── pyproject.toml
│   ├── src/weatherflow/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── cli.py
│   │   ├── config.py
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── app.py
│   │       └── schemas.py
│   └── tests/
│       ├── api/test_health.py
│       ├── contracts/test_repository_cutover.py
│       └── test_cli.py
└── docs/superpowers/
    ├── specs/2026-07-12-weatherflow-v3-design.md
    └── plans/2026-07-12-weatherflow-v3-p0-foundation.md
```

Directories for Run, Tool, Trust, Rhythm, Memory, Artifact, Tauri, Skills, MCP,
and Capability Packs are deliberately absent. Their first files belong to P1-P4
and must be introduced with the contracts that make them necessary.

---

### Task 1: Freeze the v2 baseline locally

**Files:**
- No file changes
- Create local annotated tag: `weatherflow-v2-final`

- [ ] **Step 1: Verify the execution worktree starts clean**

Run:

```bash
git status --short
git branch --show-current
git tag --list weatherflow-v2-final
```

Expected:

- `git status --short` prints nothing.
- The branch is the isolated P0 branch, not `main`.
- No existing `weatherflow-v2-final` tag is printed.

- [ ] **Step 2: Record the exact v2-final commit**

Run:

```bash
git rev-parse HEAD
git log -1 --oneline
```

Expected: `HEAD` includes the approved v3 design and this P0 plan, but no v3
runtime changes.

- [ ] **Step 3: Create the local annotated archive tag**

Run:

```bash
git tag -a weatherflow-v2-final -m "Archive WeatherFlow v2 before clean-slate v3 rewrite"
```

Expected: exit code 0.

- [ ] **Step 4: Verify the tag points to the starting commit**

Run:

```bash
test "$(git rev-parse weatherflow-v2-final^{commit})" = "$(git rev-parse HEAD)"
git tag -n1 --list weatherflow-v2-final
```

Expected: the test exits 0 and the annotation text is shown.

---

### Task 2: Seed the new Python package and write failing cutover contracts

**Files:**
- Create: `core/pyproject.toml`
- Create: `core/src/weatherflow/__init__.py`
- Create: `core/src/weatherflow/api/__init__.py`
- Create: `core/tests/contracts/test_repository_cutover.py`

- [ ] **Step 1: Create the new package directories**

Run:

```bash
mkdir -p core/src/weatherflow/api core/tests/contracts
```

Expected: exit code 0.

- [ ] **Step 2: Create the independent core package definition**

Create `core/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=80", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "weatherflow-core"
version = "3.0.0a1"
description = "Local Python harness daemon for WeatherFlow v3"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115,<1.0",
    "pydantic>=2.10,<3.0",
    "pydantic-settings>=2.7,<3.0",
    "uvicorn[standard]>=0.34,<1.0",
]

[project.optional-dependencies]
dev = [
    "httpx>=0.28,<1.0",
    "pytest>=8.3,<9.0",
    "pytest-asyncio>=0.25,<1.0",
    "ruff>=0.11,<1.0",
]

[project.scripts]
weatherflow = "weatherflow.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC"]
```

- [ ] **Step 3: Create the package version marker**

Create `core/src/weatherflow/__init__.py`:

```python
"""WeatherFlow v3 core package."""

__version__ = "3.0.0a1"

__all__ = ["__version__"]
```

Create `core/src/weatherflow/api/__init__.py`:

```python
"""HTTP API boundary for the WeatherFlow daemon."""
```

- [ ] **Step 4: Write repository cutover tests before changing the repository**

Create `core/tests/contracts/test_repository_cutover.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

REMOVED_V2_PATHS = (
    "backend",
    "cli",
    "desktop",
    "frontend",
    "mcp_servers",
    "scripts",
    "skills",
    "docker-compose.yml",
    "weatherflow-architecture-v1.md",
    "weatherflow-architecture-v2.md",
    "weatherflow-v2-roadmap.md",
)


def test_v3_authority_is_declared() -> None:
    architecture = ROOT / "weatherflow-architecture-v3.md"
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert architecture.is_file()
    assert "weatherflow-architecture-v3.md" in agents
    assert "authoritative" in agents.lower()
    assert "weatherflow-architecture-v2.md" not in agents


def test_v2_runtime_surfaces_are_removed() -> None:
    remaining = [path for path in REMOVED_V2_PATHS if (ROOT / path).exists()]
    assert remaining == []


def test_clean_v3_skeleton_exists() -> None:
    expected = (
        "core/pyproject.toml",
        "core/src/weatherflow/__init__.py",
        "docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md",
    )
    missing = [path for path in expected if not (ROOT / path).exists()]
    assert missing == []
```

- [ ] **Step 5: Run the contract test and verify the intentional red state**

Run:

```bash
uvx --from pytest pytest core/tests/contracts/test_repository_cutover.py -q
```

Expected: two tests fail:

- `test_v3_authority_is_declared` because `weatherflow-architecture-v3.md` does
  not exist and `AGENTS.md` still points to v2;
- `test_v2_runtime_surfaces_are_removed` because the v2 paths still exist.

`test_clean_v3_skeleton_exists` must pass. `uvx` is intentional here: it runs
the stdlib-only repository contract without mutating either the old v2 lockfile
or a new v3 lockfile before the cutover.

- [ ] **Step 6: Do not commit the red state**

This task intentionally ends red. Continue directly to Task 3; Task 3 creates
the minimal repository cutover that makes these tests pass.

---

### Task 3: Remove v2 and switch repository authority to v3

**Files:**
- Delete: `.claude/launch.json`
- Delete: `.env.example`
- Delete: `.env.example.ollama`
- Delete: `.github/workflows/ci.yml`
- Delete: `backend/`
- Delete: `cli/`
- Delete: `desktop/`
- Delete: `frontend/`
- Delete: `mcp_servers/`
- Delete: `scripts/`
- Delete: `skills/`
- Delete: `docker-compose.yml`
- Delete: all v2-only files under `docs/`, preserving `docs/superpowers/`
- Delete: `weatherflow-architecture-v1.md`
- Delete: `weatherflow-architecture-v2.md`
- Delete: `weatherflow-v2-roadmap.md`
- Delete: old `Makefile`, `README.md`, `pyproject.toml`, and `uv.lock`
- Create: `weatherflow-architecture-v3.md`
- Rewrite: `AGENTS.md`
- Create: `pyproject.toml`
- Modify: `.gitignore`

- [ ] **Step 1: Remove tracked v2 runtime surfaces and historical product docs**

Run:

```bash
git rm -r \
  .claude/launch.json \
  .github/workflows/ci.yml \
  backend cli desktop frontend mcp_servers scripts skills \
  docker-compose.yml \
  docs/ACCEPTANCE-v2.1.md \
  docs/ADR-001-v1-refactor.md \
  docs/ADR-002-weather-label-semantics.md \
  docs/ADR-003-v2-pivot.md \
  docs/ADR-004-v2-full-adoption.md \
  docs/ADR-006-immediate-long-term-memory.md \
  docs/DECISIONS-v2.md \
  docs/GOOGLE_CALENDAR_SETUP.md \
  docs/PHASE0-REVIEW.md \
  docs/V2-AUDIT-AND-HANDOFF.md \
  docs/assets \
  docs/interview-notes.md \
  docs/overhaul \
  weatherflow-architecture-v1.md \
  weatherflow-architecture-v2.md \
  weatherflow-v2-roadmap.md \
  .env.example \
  .env.example.ollama \
  Makefile README.md pyproject.toml uv.lock
```

Expected: Git reports only the listed tracked files as removed. The following
must still exist:

```bash
test -f docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md
test -f docs/superpowers/plans/2026-07-12-weatherflow-v3-p0-foundation.md
test -f .gitignore
test -f .gitleaksignore
```

- [ ] **Step 2: Create the authoritative v3 architecture entrypoint**

Create `weatherflow-architecture-v3.md`:

````markdown
# WeatherFlow Architecture v3

## 0. Authority

This document is the authoritative architecture entrypoint for WeatherFlow v3.
The approved detailed specification is
`docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md`.

If the two documents conflict, this file is the conflict resolver. A contract
change must update both documents in one commit and append a decision entry to
this file before runtime code changes.

WeatherFlow v2 is archived at the local Git tag `weatherflow-v2-final`. v3 has
no code, API, or data compatibility obligation to v2.

## 1. Product constitution

1. WeatherFlow is a rhythm-aware personal agent OS.
2. Human state is a runtime input, not merely a label or animation.
3. Explicit user goals outrank rhythm-derived strategy recommendations.
4. The floating companion is the primary habit surface.
5. Human weather and Agent work state use separate visual channels.
6. The command capsule is pure input; the Cockpit never auto-opens.
7. v3.0 proactivity is silent ambient presentation only.
8. Python Harness Daemon is the sole business core.
9. Tauri owns presentation and native OS bridging only.
10. Capability and authority are separate systems.
11. User data is local, inspectable, exportable, and deletable.
12. macOS is the only supported v3.0 desktop platform.

## 2. System model

```text
Tauri Desktop Shell
  -> authenticated local HTTP/WebSocket
Python Harness Daemon
  -> Run Coordinator + Agent Runtime + Capability Plane + Trust Plane
  -> Rhythm Intelligence
  -> Capability Packs
  -> Operational SQLite + Event Ledger + Memory + Artifact Store
```

The daemon is also usable through CLI and MCP. No client owns business state.

## 3. Hard contracts

1. Every command creates an idempotent Run.
2. Run status changes only through the deterministic Run Coordinator.
3. Workers are leaf agents and cannot spawn more agents.
4. Tool visibility is frozen per Run and checked again at execution.
5. Skills and MCP annotations never grant authority.
6. External writes, installs, and destructive actions require approval.
7. Unknown, unhealthy, or out-of-scope capabilities fail closed.
8. Credentials never enter model-visible or durable diagnostic data.
9. Uncertain side effects enter NEEDS_REVIEW and are not blindly retried.
10. RhythmPolicy may change execution strategy but not the user's goal.
11. Low-confidence human state projects to mixed/unknown weather.
12. Semantic indexes are derived and rebuildable.
13. User deletion and retention policy outrank append-only audit storage.
14. Cockpit and system notifications never open from state changes alone.
15. No alternate execution path may bypass the Run Coordinator or Trust Plane.

## 4. v3.0 scope

v3.0 includes the Python daemon, Tauri three-surface desktop, durable harness,
Rhythm Intelligence, risk-based supervised autonomy, Developer/Research/
Personal Operations capability packs, Skills, MCP, Agent Definitions, local
ownership, diagnostics, and macOS packaging.

v3.0 excludes Windows/Linux support, mobile/cloud/team features, content-level
desktop monitoring, recursive agent networks, a workflow canvas, broad email or
messaging catalogs, and all v2 compatibility.

## 5. Change discipline

1. Read this document and the approved detailed specification before edits.
2. Write a failing contract or behavior test before implementation.
3. Keep modules single-purpose and communicate through typed interfaces.
4. Run `make check` before every commit.
5. Contract changes update architecture and tests in the same commit.
6. Never push, publish, or merge without explicit user instruction.

## 6. Decision record

- 2026-07-12: Approved clean-slate v3 rewrite with Python core, Tauri shell,
  macOS-first delivery, no v2 compatibility, and a rhythm-aware general harness.
````

- [ ] **Step 3: Replace AGENTS.md with v3 repository guidance**

Replace `AGENTS.md` with:

````markdown
# AGENTS.md — WeatherFlow v3

## Read first

`weatherflow-architecture-v3.md` is the authoritative architecture entrypoint.
The approved detailed design is
`docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md`.

Read both before changing product contracts, runtime boundaries, authority,
human-state semantics, storage ownership, or desktop behavior.

WeatherFlow v2 is archived at Git tag `weatherflow-v2-final`. Do not restore or
copy v2 runtime code into v3. Historical behavior is not a compatibility target.

## Mental model

WeatherFlow v3 is a rhythm-aware personal agent OS:

```text
Tauri Shell -> Python Harness Daemon -> Rhythm + Capability Packs -> Local Data
```

- Tauri presents micro-weather, command input, Cockpit, and native metadata.
- Python owns every business decision and durable Run.
- RhythmPolicy changes interaction and execution strategy, never user goals.
- Capability says what exists; Trust says what may execute.

## Hard rules

- Cockpit never auto-opens.
- Human weather and Agent task state remain separate.
- v3.0 proactivity is silent.
- Workers are leaf agents.
- Skills and MCP annotations never grant authority.
- External writes, installs, and destructive actions require approval.
- Unknown or out-of-scope actions fail closed.
- Credentials never enter prompts, logs, events, memory, or artifacts.
- Uncertain side effects enter NEEDS_REVIEW, not automatic retry.
- User deletion outranks append-only retention.
- No v2 compatibility or fallback path.

## Current file map

```text
core/
  src/weatherflow/   Python daemon package
  tests/             unit, contract, and integration tests
docs/superpowers/    approved specifications and implementation plans
weatherflow-architecture-v3.md
```

Add new top-level areas only when the approved phase plan calls for them.

## Required loop

```bash
make lint
make format-check
make test
make check
```

Use TDD: failing test, observed failure, minimal implementation, observed pass.
Run the narrow test while developing and `make check` before committing.

## Change discipline

- Update architecture and tests in the same commit for contract changes.
- Keep domain logic out of HTTP, CLI, MCP, and Tauri adapters.
- Keep provider and tool implementations behind typed protocols.
- Do not create a second agent loop, workflow engine, or policy path.
- Do not push, publish, merge, or create releases without explicit instruction.
````

- [ ] **Step 4: Create the new root uv workspace metadata**

Create `pyproject.toml`:

```toml
[project]
name = "weatherflow-workspace"
version = "3.0.0a1"
description = "WeatherFlow v3 workspace metadata"
requires-python = ">=3.12"
dependencies = []

[tool.uv.workspace]
members = ["core"]
```

- [ ] **Step 5: Simplify generated-file ignores for the v3 skeleton**

Replace `.gitignore` with:

```gitignore
# Python
__pycache__/
*.py[cod]
*.so
build/
dist/
*.egg-info/
.venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/

# Local configuration and secrets
.env
.env.*
!.env.example
credentials.json
*_token.json

# WeatherFlow local state
.weatherflow/
.wf-data/

# Future desktop generated files
node_modules/
target/
*.tsbuildinfo

# Agent tooling
.worktrees/
.superpowers/

# OS and editors
.DS_Store
.vscode/
.idea/
*.log
```

- [ ] **Step 6: Run the repository cutover contract and verify green**

Run:

```bash
uvx --from pytest pytest core/tests/contracts/test_repository_cutover.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 7: Verify the removed v2 names are absent from tracked runtime paths**

Run:

```bash
test -z "$(git ls-files backend cli desktop frontend mcp_servers scripts skills)"
test ! -e weatherflow-architecture-v2.md
test -f weatherflow-architecture-v3.md
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 8: Commit the clean-slate cutover**

Run:

```bash
git add -A
git diff --cached --check
test -z "$(git diff --cached --name-only | rg '^\.env$|credential|token\.json')"
git commit -m "chore: cut over repository to WeatherFlow v3"
```

Expected: commit succeeds. The commit includes deletions, v3 authority docs,
the new package seed, and the passing cutover contract only.

---

### Task 4: Build the typed daemon configuration and health API

**Files:**
- Create: `core/tests/api/test_health.py`
- Create: `core/src/weatherflow/config.py`
- Create: `core/src/weatherflow/api/schemas.py`
- Create: `core/src/weatherflow/api/app.py`

- [ ] **Step 1: Write failing configuration and health tests**

Create `core/tests/api/test_health.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from weatherflow.api.app import create_app
from weatherflow.config import Settings


def test_settings_use_weatherflow_environment_prefix(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WF_HOST", "127.0.0.2")
    monkeypatch.setenv("WF_PORT", "9876")
    monkeypatch.setenv("WF_DATA_DIR", str(tmp_path))

    settings = Settings()

    assert settings.host == "127.0.0.2"
    assert settings.port == 9876
    assert settings.data_dir == tmp_path


def test_health_returns_typed_core_identity(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    client = TestClient(create_app(settings))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "weatherflow-core",
        "version": "3.0.0a1",
    }
```

- [ ] **Step 2: Run the tests and observe the missing-module failure**

Run:

```bash
uv run --project core --extra dev pytest core/tests/api/test_health.py -q
```

Expected: collection fails because `weatherflow.api.app` and
`weatherflow.config` do not exist.

- [ ] **Step 3: Implement immutable typed settings**

Create `core/src/weatherflow/config.py`:

```python
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration for the local WeatherFlow daemon."""

    model_config = SettingsConfigDict(
        env_prefix="WF_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    data_dir: Path = Path("~/.local/share/weatherflow").expanduser()
    log_level: str = "INFO"
```

- [ ] **Step 4: Implement the health response schema**

Create `core/src/weatherflow/api/schemas.py`:

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    service: Literal["weatherflow-core"] = "weatherflow-core"
    version: str
```

- [ ] **Step 5: Implement the application factory**

Create `core/src/weatherflow/api/app.py`:

```python
from fastapi import FastAPI

from weatherflow import __version__
from weatherflow.api.schemas import HealthResponse
from weatherflow.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    app = FastAPI(title="WeatherFlow Core", version=__version__)
    app.state.settings = resolved_settings

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(version=__version__)

    return app


app = create_app()
```

- [ ] **Step 6: Run the focused tests and verify green**

Run:

```bash
uv run --project core --extra dev pytest core/tests/api/test_health.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 7: Run Ruff on the new application code**

Run:

```bash
uv run --project core --extra dev ruff check core/src core/tests/api
uv run --project core --extra dev ruff format --check core/src core/tests/api
```

Expected: both commands exit 0.

- [ ] **Step 8: Commit the health API**

Run:

```bash
git add core/src/weatherflow/config.py core/src/weatherflow/api core/tests/api
git diff --cached --check
git commit -m "feat: add WeatherFlow v3 health API"
```

---

### Task 5: Add the daemon CLI entrypoint

**Files:**
- Create: `core/tests/test_cli.py`
- Create: `core/src/weatherflow/cli.py`
- Create: `core/src/weatherflow/__main__.py`

- [ ] **Step 1: Write failing CLI tests**

Create `core/tests/test_cli.py`:

```python
from weatherflow import __version__
from weatherflow.cli import build_parser, main


def test_version_command_prints_core_version(capsys) -> None:
    exit_code = main(["--version"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_serve_command_uses_settings_defaults(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: str, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("weatherflow.cli.uvicorn.run", fake_run)

    exit_code = main(["serve"])

    assert exit_code == 0
    assert captured == {
        "app": "weatherflow.api.app:app",
        "host": "127.0.0.1",
        "port": 8765,
        "reload": False,
        "log_level": "info",
    }


def test_parser_requires_a_command_without_version() -> None:
    parser = build_parser()

    args = parser.parse_args(["serve", "--port", "9000", "--reload"])

    assert args.command == "serve"
    assert args.port == 9000
    assert args.reload is True
```

- [ ] **Step 2: Run the CLI tests and observe the missing-module failure**

Run:

```bash
uv run --project core --extra dev pytest core/tests/test_cli.py -q
```

Expected: collection fails because `weatherflow.cli` does not exist.

- [ ] **Step 3: Implement the CLI**

Create `core/src/weatherflow/cli.py`:

```python
import argparse
from collections.abc import Sequence

import uvicorn

from weatherflow import __version__
from weatherflow.config import Settings


def build_parser() -> argparse.ArgumentParser:
    settings = Settings()
    parser = argparse.ArgumentParser(prog="weatherflow")
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Run the local WeatherFlow daemon")
    serve.add_argument("--host", default=settings.host)
    serve.add_argument("--port", type=int, default=settings.port)
    serve.add_argument("--reload", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.command != "serve":
        parser.error("a command is required")

    settings = Settings(host=args.host, port=args.port)
    uvicorn.run(
        "weatherflow.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )
    return 0
```

- [ ] **Step 4: Add `python -m weatherflow` support**

Create `core/src/weatherflow/__main__.py`:

```python
from weatherflow.cli import main


raise SystemExit(main())
```

- [ ] **Step 5: Run the focused CLI tests**

Run:

```bash
uv run --project core --extra dev pytest core/tests/test_cli.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 6: Run real entrypoint smoke checks**

Run:

```bash
uv run --project core weatherflow --version
uv run --project core python -m weatherflow --version
```

Expected: both commands print exactly `3.0.0a1`.

- [ ] **Step 7: Run Ruff and commit**

Run:

```bash
uv run --project core --extra dev ruff check core/src core/tests/test_cli.py
uv run --project core --extra dev ruff format --check core/src core/tests/test_cli.py
git add core/src/weatherflow/cli.py core/src/weatherflow/__main__.py core/tests/test_cli.py
git diff --cached --check
git commit -m "feat: add WeatherFlow daemon CLI"
```

---

### Task 6: Establish developer commands, CI, environment example, and README

**Files:**
- Create: `.env.example`
- Create: `Makefile`
- Create: `README.md`
- Create: `.github/workflows/ci.yml`
- Generate: `uv.lock`

- [ ] **Step 1: Create the environment example and CI directory**

Run:

```bash
mkdir -p .github/workflows
```

Expected: exit code 0.

Create `.env.example`:

```dotenv
WF_HOST=127.0.0.1
WF_PORT=8765
WF_DATA_DIR=~/.local/share/weatherflow
WF_LOG_LEVEL=INFO
```

- [ ] **Step 2: Create the root developer command surface**

Create `Makefile`:

```makefile
.PHONY: install lint format-check test check dev clean

PY := uv run --package weatherflow-core --extra dev

install:
	uv sync --all-packages --all-extras

lint:
	$(PY) ruff check core/src core/tests

format-check:
	$(PY) ruff format --check core/src core/tests

test:
	$(PY) pytest core/tests -q

check: lint format-check test

dev:
	uv run --package weatherflow-core weatherflow serve --reload

clean:
	find core -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '*.egg-info' \) -prune -exec rm -rf {} +
	find core -type f -name '*.pyc' -delete
```

- [ ] **Step 3: Replace CI with the P0 Python gate**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: ["main"]
  pull_request:
    branches: ["main"]

jobs:
  core:
    name: Python Core
    runs-on: ubuntu-latest

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        run: python -m pip install uv

      - name: Sync locked workspace
        run: uv sync --all-packages --all-extras --locked

      - name: Lint
        run: uv run --package weatherflow-core --extra dev ruff check core/src core/tests

      - name: Check formatting
        run: uv run --package weatherflow-core --extra dev ruff format --check core/src core/tests

      - name: Test
        run: uv run --package weatherflow-core --extra dev pytest core/tests -q
```

- [ ] **Step 4: Create the P0 README**

Create `README.md`:

````markdown
# WeatherFlow v3

WeatherFlow is a rhythm-aware personal agent OS. v3 is a clean-slate rewrite
with a local Python harness daemon and a macOS-first Tauri desktop shell.

P0 provides the new authoritative architecture, package boundary, health API,
CLI entrypoint, and quality gates. Durable Runs, Trust, Rhythm Intelligence,
the desktop shell, and Capability Packs arrive in P1-P4.

## Read first

- `weatherflow-architecture-v3.md`
- `docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md`

WeatherFlow v2 is preserved in Git history and the local tag
`weatherflow-v2-final`; it is not a compatibility target.

## Requirements

- Python 3.12
- uv

## Quick start

```bash
cp .env.example .env
make install
make check
make dev
```

The daemon listens on `127.0.0.1:8765` by default.

```bash
curl http://127.0.0.1:8765/health
```

Expected response:

```json
{"status":"ok","service":"weatherflow-core","version":"3.0.0a1"}
```

## Current repository

```text
core/                    Python daemon package and tests
docs/superpowers/        Approved design and implementation plans
weatherflow-architecture-v3.md
```

Do not restore or copy v2 runtime modules into the v3 package.
````

- [ ] **Step 5: Generate and verify the new lockfile**

Run:

```bash
uv lock
uv sync --all-packages --all-extras --locked
```

Expected: `uv.lock` is created for the root workspace with `weatherflow-core` as
the only workspace package.

- [ ] **Step 6: Run the complete local quality gate**

Run:

```bash
make check
```

Expected:

- Ruff lint exits 0.
- Ruff format check exits 0.
- All core tests pass.

- [ ] **Step 7: Verify the lockfile and README match the package**

Run:

```bash
rg -n 'name = "weatherflow-core"' uv.lock
uv run --package weatherflow-core weatherflow --version
git diff --check
```

Expected: the lockfile contains `weatherflow-core`, the CLI prints `3.0.0a1`,
and the diff check exits 0.

- [ ] **Step 8: Commit the P0 developer surface**

Run:

```bash
git add .env.example .github/workflows/ci.yml Makefile README.md uv.lock
git diff --cached --check
git commit -m "build: establish WeatherFlow v3 quality gates"
```

---

### Task 7: Run the P0 acceptance audit

**Files:**
- No changes expected

- [ ] **Step 1: Verify the local archive exists and was not pushed by the plan**

Run:

```bash
git tag -n1 --list weatherflow-v2-final
git remote -v
```

Expected: the local tag is present. Do not run `git push`.

- [ ] **Step 2: Verify the clean-slate repository contract**

Run:

```bash
uv run --package weatherflow-core --extra dev pytest \
  core/tests/contracts/test_repository_cutover.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 3: Verify the entire P0 gate from a locked environment**

Run:

```bash
uv sync --all-packages --all-extras --locked
make check
```

Expected: sync, lint, format check, and all tests pass with zero failures.

- [ ] **Step 4: Verify runtime imports and public entrypoints**

Run:

```bash
uv run --package weatherflow-core python -c "from weatherflow.api.app import app; print(app.title)"
uv run --package weatherflow-core weatherflow --version
```

Expected:

```text
WeatherFlow Core
3.0.0a1
```

- [ ] **Step 5: Verify only the approved P0 tree remains tracked**

Run:

```bash
git status --short
git ls-files | awk -F/ '{print $1}' | sort -u
```

Expected:

- `git status --short` prints nothing.
- Top-level tracked paths are limited to v3 configuration/docs, `core`, and
  repository metadata.
- None of `backend`, `cli`, `desktop`, `frontend`, `mcp_servers`, `scripts`, or
  `skills` is listed.

- [ ] **Step 6: Inspect commit scope**

Run:

```bash
git log --oneline weatherflow-v2-final..HEAD
```

Expected: exactly these P0 implementation commits appear after the archive tag:

```text
build: establish WeatherFlow v3 quality gates
feat: add WeatherFlow daemon CLI
feat: add WeatherFlow v3 health API
chore: cut over repository to WeatherFlow v3
```

Do not create a final empty commit. P0 ends when the audit is green.

---

## P0 completion handoff

P0 is complete only when:

- the v2 baseline is recoverable from the local `weatherflow-v2-final` tag;
- all v2 runtime surfaces and authority docs are absent from the v3 branch;
- `weatherflow-architecture-v3.md` and `AGENTS.md` agree;
- the new `weatherflow-core` package imports and serves a typed health response;
- CLI and `python -m weatherflow` entrypoints work;
- `make check` passes from the locked workspace;
- Git status is clean;
- nothing has been pushed.

After P0, write a separate P1 implementation plan for Operational Store, Event
Ledger, Run Coordinator, shared Agent turn loop, Workspace, Capability Resolver,
Trust Plane, Approval, and Artifact Store. Do not start those modules from this
plan.
