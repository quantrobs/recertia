"""schema/*.schema.json MUST be exactly what contracts/ generates (ADR-0009, B5)."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_schema_directory_has_no_drift_from_contracts():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_schemas.py"), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"schema/ has drifted from contracts/; run scripts/generate_schemas.py and commit.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_schema_ids_use_public_github_org():
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.generate_schemas import MODELS, SCHEMA_ID_BASE

    assert SCHEMA_ID_BASE == "https://github.com/recertia/recertia/schema"
    assert ("quant" + "robs") not in SCHEMA_ID_BASE
    for filename, model in MODELS.items():
        text = (REPO_ROOT / "schema" / filename).read_text(encoding="utf-8")
        assert f'"$id": "{SCHEMA_ID_BASE}/{model.__name__}"' in text


def test_tracked_sources_have_no_quantrobs_identity():
    """Old GitHub org leftovers must not reappear in public-facing sources."""
    skip_dir_names = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".recertia",
        "node_modules",
    }
    # This file names the forbidden tokens on purpose.
    skip_files = {REPO_ROOT / "tests" / "contracts" / "test_schema_generation.py"}
    suffixes = {".md", ".py", ".json", ".toml", ".html", ".yml", ".yaml", ".txt"}
    needle = "quant" + "robs"
    old_repo = "fan" + "dea"
    hits: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if path in skip_files:
            continue
        if any(part in skip_dir_names for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        if needle in text or old_repo in text:
            hits.append(str(path.relative_to(REPO_ROOT)))
    assert hits == [], f"old-org leftovers in: {', '.join(hits)}"


def test_readme_and_pyproject_declare_polyform_license():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "PolyForm Noncommercial" in readme
    assert "PolyForm Noncommercial" in license_text
    assert license_text.lstrip().startswith("# PolyForm Noncommercial License 1.0.0")
    assert "PolyForm-Noncommercial-1.0.0" in pyproject
    assert (REPO_ROOT / "NOTICE").is_file()
    assert "Copyright (c) 2026 Robert Schmidt" in (REPO_ROOT / "NOTICE").read_text(encoding="utf-8")
    assert (REPO_ROOT / "SECURITY.md").is_file()
    assert (REPO_ROOT / "CONTRIBUTING.md").is_file()
    assert (REPO_ROOT / "CHANGELOG.md").is_file()
    assert (REPO_ROOT / "assets" / "mark.svg").is_file()
    assert (REPO_ROOT / "assets" / "logo.svg").is_file()
    assert 'Homepage = "https://github.com/recertia/recertia"' in pyproject
    assert 'Repository = "https://github.com/recertia/recertia"' in pyproject
    assert "Documentation =" in pyproject
    assert "Changelog =" in pyproject
    assert "github.com/recertia/recertia" in (REPO_ROOT / "CONTRIBUTING.md").read_text(
        encoding="utf-8"
    )
    assert "CONTRIBUTING.md" in agents
    assert "not the contributor guide" in agents.lower().replace("*", "")


def test_pyproject_toml_parses_and_pins_canonical_github_repo():
    """Duplicate keys (e.g. two `license =` lines) must not silently break pip/CI."""
    import tomllib

    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    urls = data["project"]["urls"]
    assert urls["Homepage"] == "https://github.com/recertia/recertia"
    assert urls["Repository"] == "https://github.com/recertia/recertia"
    assert data["project"]["license"] == "PolyForm-Noncommercial-1.0.0"


def test_living_docs_use_canonical_github_repo_not_placeholders():
    """Public clone/PR identity must stay recertia/recertia (not a generic placeholder)."""
    skip_dir_names = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".recertia",
        "node_modules",
        "archive",
    }
    skip_files = {REPO_ROOT / "tests" / "contracts" / "test_schema_generation.py"}
    suffixes = {".md", ".py", ".toml", ".yml", ".yaml", ".html"}
    placeholder = "github.com/your-org/"
    hits: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if path in skip_files:
            continue
        if any(part in skip_dir_names for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if placeholder in text:
            hits.append(str(path.relative_to(REPO_ROOT)))
    assert hits == [], f"placeholder GitHub owner/repo in: {', '.join(hits)}"


def test_research_survey_files_are_not_git_lfs_pointers():
    gitattributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "research/" not in gitattributes or "filter=lfs" not in gitattributes
    paths = [
        REPO_ROOT / "research" / "preprints-self-improving-agents.xlsx",
        REPO_ROOT / "research" / "preprints-score10-reference-lists.xlsx",
        REPO_ROOT / "research" / "preprints-self-improving-agents.scored.json",
        REPO_ROOT / "research" / "preprints-score10-reference-lists.scored.json",
        REPO_ROOT / "research" / "score10-references" / "score10-references.json",
    ]
    lfs_prefix = b"version https://git-lfs.github.com/spec/v1"
    missing = [str(p.relative_to(REPO_ROOT)) for p in paths if not p.is_file()]
    assert missing == [], f"missing research files: {missing}"
    pointers = [
        str(p.relative_to(REPO_ROOT)) for p in paths if p.read_bytes().startswith(lfs_prefix)
    ]
    assert pointers == [], f"research files still Git LFS pointers: {pointers}"


def test_canonical_examples_have_no_drift_from_contracts_examples():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "export_examples.py"), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"skills/bump-python-dep/v3/*.json drifted from contracts/examples.py; "
        f"run scripts/export_examples.py and commit.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_architecture2_has_no_drift_from_topic_files():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_architecture2.py"), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"docs/architecture2.md has drifted from topic files; "
        f"run scripts/generate_architecture2.py and commit.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_architecture2_includes_architecture_and_specifications():
    text = (REPO_ROOT / "docs" / "architecture2.md").read_text(encoding="utf-8")
    assert "# Recertia architecture2" in text
    assert "# Part I — Architecture" in text
    assert "# Part II — Specifications" in text
    assert "architecture/overview.md" in text
    assert "specifications/core-entities.md" in text
    assert "adr/0001-graph-with-loops.md" in text
