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
