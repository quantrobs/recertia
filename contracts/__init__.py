"""Normative structural contracts for Recertia (ADR-0009: contracts as code).

These Pydantic models are the single source of truth for the data model described in
``docs/specifications.md``. ``schema/*.schema.json`` is generated from them
(``scripts/generate_schemas.py``); never hand-edit the schema files.

This package intentionally exists ahead of ``src/recertia/`` (see the repository status in
``README.md``): it is specification tooling that resolves the structural blockers in
``docs/refactor-plan.md`` (B1, B2, B3, B4, B5), not the graph engine, solver, or any node
implementation. When ``src/recertia/`` is scaffolded at M0, it imports from here rather than
redefining these types.
"""
