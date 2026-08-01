"""Goal templates for Pilot (C4)."""

from __future__ import annotations

from typing import Any

from contracts.goal import Goal

TEMPLATES: dict[str, dict[str, Any]] = {
    "add-gitignore-pyc": {
        "title": "Ignore *.pyc",
        "description": "Ensure .gitignore contains *.pyc",
        "goal": {
            "goal_id": "tmpl-gitignore-pyc",
            "desired": [
                {
                    "id": "gitignore-exists",
                    "kind": "file_exists",
                    "path": ".gitignore",
                    "weight": 1.0,
                },
                {
                    "id": "pyc-ignored",
                    "kind": "file_contains",
                    "path": ".gitignore",
                    "pattern": "\\*\\.pyc",
                    "weight": 1.0,
                },
            ],
            "constraints": [],
            "context": "Add *.pyc to .gitignore if missing",
            "task_class": "repo-chore",
        },
    },
    "add-editorconfig": {
        "title": "Add EditorConfig",
        "description": "Root .editorconfig with Python indent settings",
        "goal": {
            "goal_id": "tmpl-editorconfig",
            "desired": [
                {
                    "id": "ec-exists",
                    "kind": "file_exists",
                    "path": ".editorconfig",
                    "weight": 1.0,
                },
                {
                    "id": "ec-python",
                    "kind": "file_contains",
                    "path": ".editorconfig",
                    "pattern": "\\[\\*\\.py\\]",
                    "weight": 1.0,
                },
            ],
            "constraints": [],
            "context": "Add a root EditorConfig with Python indent settings",
            "task_class": "repo-chore",
        },
    },
    "add-pytest-config": {
        "title": "Add pytest.ini",
        "description": "pytest.ini with testpaths=tests",
        "goal": {
            "goal_id": "tmpl-pytest-ini",
            "desired": [
                {
                    "id": "pytest-ini",
                    "kind": "file_exists",
                    "path": "pytest.ini",
                    "weight": 1.0,
                },
                {
                    "id": "testpaths",
                    "kind": "file_contains",
                    "path": "pytest.ini",
                    "pattern": "testpaths\\s*=\\s*tests",
                    "weight": 1.0,
                },
            ],
            "constraints": [],
            "context": "Add pytest.ini setting testpaths to tests",
            "task_class": "repo-chore",
        },
    },
}


def list_templates() -> list[dict[str, Any]]:
    return [
        {"id": tid, "title": meta["title"], "description": meta["description"]}
        for tid, meta in TEMPLATES.items()
    ]


def get_template_goal(template_id: str) -> Goal:
    meta = TEMPLATES.get(template_id)
    if meta is None:
        raise KeyError(template_id)
    return Goal.model_validate(meta["goal"])
