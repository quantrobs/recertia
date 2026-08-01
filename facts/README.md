# Semantic facts (`facts/`)

Canonical layout: `facts/<scope>/<slug>.json` (scopes: `run`, `project`, `org`, `global`).

This directory starts empty on purpose. The first write creates the scope subdirectory:

- Runtime: `FactStore(root="facts").write(fact)` mkdirs `facts/<scope>/` and writes `<slug>.json`.
- Contradictions are retained beside the original (see `recertia.memory.semantic.FactStore`).

Do not hand-author facts without provenance; prefer distillation or an explicit human assertion.
