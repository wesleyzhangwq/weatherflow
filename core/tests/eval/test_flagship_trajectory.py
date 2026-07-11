from pathlib import Path

from weatherflow.eval import run_flagship_fixture


async def test_overloaded_release_trajectory_passes_all_deterministic_checks(
    tmp_path: Path,
) -> None:
    result = await run_flagship_fixture(tmp_path)

    assert result.report.passed
    assert all(check.passed for check in result.report.checks)
    assert result.release_calls_before_approval == 0
    assert result.release_calls_after_approval == 1
    assert result.release_calls_after_replay == 1
    assert result.model_calls_after_replay == result.model_calls_after_completion
    assert result.report.metric("worker_count") == 3
    assert result.report.metric("artifact_count") >= 3
