import re

from weatherflow.operations.models import SecurityFinding, SecurityScan
from weatherflow.storage import Database

FORBIDDEN_FIELDS = ("screenshot", "window_title", "keystrokes", "clipboard")
SECRET_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{8,}", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
)


class SecurityScanner:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def scan(self) -> SecurityScan:
        sources = {
            "events": ("id", ("payload",)),
            "checkpoints": ("run_id", ("transcript", "state")),
            "episodic_memories": ("id", ("summary", "source_event_ids", "tags")),
            "profile_assertions": ("id", ("claim", "evidence_event_ids")),
            "workspaces": ("id", ("config",)),
            "artifacts": ("id", ("validation",)),
        }
        findings: list[SecurityFinding] = []
        async with self.database.connect() as connection:
            for table, (identity, fields) in sources.items():
                columns = ", ".join((identity, *fields))
                rows = await (await connection.execute(f"SELECT {columns} FROM {table}")).fetchall()
                for row in rows:
                    for field in fields:
                        value = str(row[field])
                        for forbidden in FORBIDDEN_FIELDS:
                            if re.search(rf'["\']{forbidden}["\']\s*:', value):
                                findings.append(
                                    SecurityFinding(
                                        table=table,
                                        row_id=str(row[identity]),
                                        field=field,
                                        kind="forbidden_sensor_field",
                                    )
                                )
                                break
                        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
                            findings.append(
                                SecurityFinding(
                                    table=table,
                                    row_id=str(row[identity]),
                                    field=field,
                                    kind="secret_value",
                                )
                            )
        unique = {(item.table, item.row_id, item.field, item.kind): item for item in findings}
        return SecurityScan(findings=tuple(unique[key] for key in sorted(unique)))
