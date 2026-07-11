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
