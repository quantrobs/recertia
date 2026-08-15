"""Generated schema/*.schema.json must be valid Draft 2020-12 and accept the canonical example."""

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_every_generated_schema_is_itself_valid():
    schema_dir = REPO_ROOT / "schema"
    for path in schema_dir.glob("*.schema.json"):
        schema = _load(path)
        jsonschema.Draft202012Validator.check_schema(schema)


def test_canonical_skill_version_validates_against_generated_schema():
    schema = _load(REPO_ROOT / "schema" / "skill_version.schema.json")
    example = _load(REPO_ROOT / "skills" / "bump-python-dep" / "v3" / "version.json")
    jsonschema.Draft202012Validator(schema).validate(example)


def test_canonical_skill_status_validates_against_generated_schema():
    schema = _load(REPO_ROOT / "schema" / "skill_status.schema.json")
    example = _load(REPO_ROOT / "skills" / "bump-python-dep" / "v3" / "status.json")
    jsonschema.Draft202012Validator(schema).validate(example)


def test_canonical_skill_stats_validates_against_generated_schema():
    schema = _load(REPO_ROOT / "schema" / "skill_stats.schema.json")
    example = _load(REPO_ROOT / "skills" / "bump-python-dep" / "v3" / "stats.json")
    jsonschema.Draft202012Validator(schema).validate(example)
