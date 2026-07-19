from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_activity_summary_and_connector_calendar_import_in_a_fresh_process() -> None:
    project_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from weatherflow.connectors.calendar import ComposioCalendarAdapter; "
                "from weatherflow.activity.summarization import ActivitySummaryAnalyzer"
            ),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
