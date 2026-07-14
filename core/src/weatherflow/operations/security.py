import asyncio
import json
import re
from pathlib import Path

from weatherflow.operations.models import SecurityFinding, SecurityScan
from weatherflow.storage import Database

FORBIDDEN_FIELDS = ("screenshot", "window_title", "keystrokes", "clipboard")
SECRET_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(
        r"\b(?:github_pat_[A-Za-z0-9_]{10,}|gh[pousr]_[A-Za-z0-9_]{10,}|"
        r"sk-[A-Za-z0-9_-]{8,}|AKIA[A-Z0-9]{16}|"
        r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:access[_-]?token|refresh[_-]?token|api[_-]?key|apikey|password|passwd|"
        r"secret|authorization|cookie)\b[\"']?\s*[:=]\s*[\"']?"
        r"(?!\[redacted\]|<redacted>)[^\s\"',;]{8,}",
        re.IGNORECASE,
    ),
)


class SecurityScanner:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def scan(self) -> SecurityScan:
        sources = {
            "events": ("id", ("payload",)),
            "runs": (
                "id",
                ("user_intent", "budget", "result_summary", "error_class", "error_message"),
            ),
            "actions": (
                "id",
                ("arguments", "preview", "result", "error_class", "error_message"),
            ),
            "approvals": ("id", ("rationale",)),
            "checkpoints": ("run_id", ("transcript", "state")),
            "episodic_memories": ("id", ("summary", "source_event_ids", "tags")),
            "profile_assertions": ("id", ("claim", "evidence_event_ids")),
            "workspaces": ("id", ("config",)),
            "artifacts": ("id", ("validation",)),
            "checkpoint_quarantine": ("run_id", ("raw_payload",)),
            "automations": ("id", ("name", "config")),
            "connector_accounts": ("id", ("external_account_id", "config")),
            "connection_attempts": ("id", ("config",)),
            "connector_bindings": ("workspace_id", ("config",)),
            "connector_snapshots": ("workspace_id", ("snapshot",)),
            "model_configurations": (
                "workspace_id",
                ("provider", "model", "base_url", "credential_ref"),
            ),
            "run_model_routes": ("run_id", ("base_url", "credential_ref")),
        }
        findings: list[SecurityFinding] = []
        artifact_rows = []
        async with self.database.connect() as connection:
            for table, (identity, fields) in sources.items():
                columns = ", ".join((identity, *fields))
                rows = await (await connection.execute(f"SELECT {columns} FROM {table}")).fetchall()
                for row in rows:
                    for field in fields:
                        value = str(row[field])
                        for kind in _finding_kinds(value):
                            findings.append(
                                SecurityFinding(
                                    table=table,
                                    row_id=str(row[identity]),
                                    field=field,
                                    kind=kind,
                                )
                            )
            artifact_rows = await (
                await connection.execute(
                    """
                    SELECT a.id, a.relative_path, w.config AS workspace_config
                    FROM artifacts a
                    JOIN runs r ON r.id = a.run_id
                    JOIN workspaces w ON w.id = r.workspace_id
                    """
                )
            ).fetchall()
        for row in artifact_rows:
            try:
                workspace_config = json.loads(row["workspace_config"])
                artifact_root = workspace_config["artifact_root"]
                if not isinstance(artifact_root, str):
                    raise TypeError("artifact root is not a string")
                kinds = await asyncio.to_thread(
                    _artifact_finding_kinds,
                    Path(artifact_root),
                    Path(row["relative_path"]),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                kinds = frozenset({"artifact_path_invalid"})
            for kind in kinds:
                findings.append(
                    SecurityFinding(
                        table="artifacts",
                        row_id=str(row["id"]),
                        field="content",
                        kind=kind,
                    )
                )
        unique = {(item.table, item.row_id, item.field, item.kind): item for item in findings}
        return SecurityScan(findings=tuple(unique[key] for key in sorted(unique)))


def _finding_kinds(value: str) -> frozenset[str]:
    findings: set[str] = set()
    if any(re.search(rf'["\']{field}["\']\s*:', value) for field in FORBIDDEN_FIELDS):
        findings.add("forbidden_sensor_field")
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        findings.add("secret_value")
    return frozenset(findings)


def _artifact_finding_kinds(root: Path, relative_path: Path) -> frozenset[str]:
    resolved_root = root.resolve()
    target = (resolved_root / relative_path).resolve()
    if not target.is_relative_to(resolved_root):
        return frozenset({"artifact_path_invalid"})
    findings: set[str] = set()
    try:
        with target.open("rb") as artifact:
            tail = ""
            while chunk := artifact.read(64 * 1024):
                window = tail + chunk.decode("latin1")
                findings.update(_finding_kinds(window))
                if findings == {"forbidden_sensor_field", "secret_value"}:
                    break
                tail = window[-1024:]
    except OSError:
        return frozenset({"artifact_unreadable"})
    return frozenset(findings)
