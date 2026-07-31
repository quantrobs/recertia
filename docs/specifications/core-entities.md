# Fandea Specifications: 1. Core entities

## 1. Core entities

Per [ADR-0007](../adr/0007-skill-identity-status-and-stats-split.md), a skill version's identity,
status, and statistics are three records with three different mutability regimes, not one.

| Entity | Identity | Mutability | Contract |
| --- | --- | --- | --- |
| `Task` | `task_id` (ULID) | Immutable after intake | [`contracts/run.py:Task`](../../contracts/run.py) |
| `Run` (`RunState`) | `run_id` (ULID) | Append-only status transitions | [`contracts/run.py:RunState`](../../contracts/run.py) |
| `Attempt` | `(run_id, attempt_no)` | Immutable once closed | — |
| `Transcript` | content hash | Immutable | — |
| `SkillVersion` | `(skill_id, version)` | **Immutable once written** | [`contracts/skill.py`](../../contracts/skill.py) |
| `SkillStatus` | `(skill_id, version)` | Append-only event log, projected | [`contracts/status.py`](../../contracts/status.py) |
| `SkillStats` | `(skill_id, version)` | Derived, rebuildable (T0) | [`contracts/stats.py`](../../contracts/stats.py) |
| `TaskCriterion` | `(run_id, criterion_id)` | Immutable after `criteria_locked_at` | [`contracts/criteria.py`](../../contracts/criteria.py) |
| `SkillCertificationCriterion` | `(skill_id, version, criterion_id)` | Immutable once written, versioned with the skill | [`contracts/criteria.py`](../../contracts/criteria.py) |
| `ValidationResult` (`CriterionResult`) | `(attempt_id, criterion_id)` | Immutable | [`contracts/criteria.py`](../../contracts/criteria.py) |
| `ReviewDecision` | `decision_id` | Immutable | — |

The immutability of `SkillVersion` is the load-bearing rule. Evolution MUST produce
version `N+1` with `supersedes: N`; nothing may edit version `N` in place. Rollback is
therefore always available and always cheap. That rule now applies to a document that holds
**only** identity, intent, steps, certification criteria, provenance, and the one-time hygiene
gate — `lifecycle`, `active`, `predictive_trust`, and `contribution` live on `SkillStatus` and
`SkillStats` instead, which change on their own cadence without violating anything (ADR-0007).

## 2. Skill contracts

Per [ADR-0007](../adr/0007-skill-identity-status-and-stats-split.md), one skill version is three
records, not one document. All three are generated from
[`contracts/skill.py`](../../contracts/skill.py), [`contracts/status.py`](../../contracts/status.py),
and [`contracts/stats.py`](../../contracts/stats.py); the JSON below is the canonical
`bump-python-dep@3` example, exported by `scripts/export_examples.py` to
`skills/bump-python-dep/v3/*.json` and asserted by
[`tests/contracts/test_examples.py`](../../tests/contracts/test_examples.py) to pass the
`approved-skill` profile, not merely to parse. Null-valued optional fields are omitted below for
readability; the canonical files have them explicitly.

### 2.1 `SkillVersion` (immutable)

Canonical form is JSON at `skills/<skill_id>/v<version>/version.json`, validated against
[`schema/skill_version.schema.json`](../../schema/skill_version.schema.json).

```json
{
  "schema_version": "2.0",
  "skill_id": "bump-python-dep",
  "version": 3,
  "supersedes": 2,
  "title": "Bump a pinned Python dependency and repair fallout",
  "intent": "Raise a pinned dependency to a target version, then fix imports, type errors and test failures caused by the bump.",
  "task_class": "repo-chore",
  "tags": ["python", "dependencies", "lockfile"],
  "parameters": [
    { "name": "package", "type": "string", "required": true },
    { "name": "target_version", "type": "string", "required": false,
      "description": "Omit to take the latest compatible release." }
  ],
  "preconditions": [
    { "kind": "file_exists", "value": "pyproject.toml" },
    { "kind": "probe", "value": "python_module_available",
      "arguments": { "module": "tomllib" } }
  ],
  "steps": [
    { "id": "locate", "tool": "grep", "intent": "Find the current pin for {{package}}.",
      "outputs": [{ "name": "current_pin", "type": "string", "value_from": "stdout" }] },
    { "id": "changelog", "tool": "fetch", "intent": "Read the upstream changelog for breaking changes.",
      "outputs": [{ "name": "notes", "type": "string", "value_from": "stdout" }],
      "resources": [{ "kind": "rate_limit", "id": "pypi", "mode": "write" }] },
    { "id": "edit", "tool": "edit_file", "intent": "Raise the pin to {{target_version}}.",
      "input_bindings": [
        { "input": "current_pin", "source_step": "locate", "output": "current_pin" }
      ],
      "outputs": [{ "name": "changed", "type": "number", "value_from": "exit_code" }],
      "resources": [{ "kind": "file", "id": "pyproject.toml", "mode": "write" }] },
    { "id": "sync", "tool": "shell", "intent": "Regenerate the lockfile.",
      "input_bindings": [
        { "input": "changed", "source_step": "edit", "output": "changed" }
      ],
      "outputs": [{ "name": "synced", "type": "number", "value_from": "exit_code" }] },
    { "id": "repair", "tool": "agent_subtask",
      "intent": "Fix breakage surfaced by the type checker and tests.",
      "input_bindings": [
        { "input": "sync_status", "source_step": "sync", "output": "synced" },
        { "input": "changelog", "source_step": "changelog", "output": "notes" }
      ],
      "loop": { "until": "criteria_pass", "max_iterations": 3 } }
  ],
  "certification_criteria": [
    { "id": "install", "kind": "command", "run": "uv sync --frozen", "expect_exit": 0, "weight": 1.0,
      "preregistered": true, "sensitivity_proof": { "criterion_id": "install",
      "negative_fixture": "pre-bump workspace with a broken lockfile", "rejected": true,
      "checked_at": "2026-07-30T15:22:11Z" } },
    { "id": "types", "kind": "command", "run": "mypy .", "expect_exit": 0, "weight": 1.0,
      "preregistered": true, "sensitivity_proof": { "criterion_id": "types",
      "negative_fixture": "v2's stale-lockfile regression case", "rejected": true,
      "checked_at": "2026-07-30T15:22:11Z" } },
    { "id": "tests", "kind": "command", "run": "pytest -q", "expect_exit": 0, "weight": 1.0,
      "preregistered": true, "sensitivity_proof": { "criterion_id": "tests",
      "negative_fixture": "pre-bump workspace, unpatched", "rejected": true,
      "checked_at": "2026-07-30T15:22:11Z" } },
    { "id": "scope", "kind": "judge", "rubric": "Only dependency-related files changed.",
      "isolation": "fresh_context", "lens": "scope", "weight": 0.3, "preregistered": true }
  ],
  "failure_modes": [
    { "symptom": "Transitive pin conflict.", "response": "Relax the narrowest conflicting constraint, then re-run install." }
  ],
  "provenance": {
    "distilled_from_run": "01JD3K0000000000000000RUN3",
    "distilled_at": "2026-07-30T15:22:11Z",
    "curation": "human_authored",
    "derivation": "hand_authored",
    "evolved_because": "v2 left the lockfile stale when the bump was a no-op."
  },
  "hygiene": { "secret_scan": "passed", "scanned_at": "2026-07-30T15:22:11Z" }
}
```

### 2.2 `SkillStatus` (append-only, projected)

Canonical form is JSON at `skills/<skill_id>/v<version>/status.json`, validated against
[`schema/skill_status.schema.json`](../../schema/skill_status.schema.json). This is a projection of
an append-only lifecycle event log to its current state; the projection is what is stored and
retrieved, and it is what the diagram in `architecture/library-lifecycle.md` §7.1 depicts
transitions of.

```json
{
  "skill_id": "bump-python-dep",
  "version": 3,
  "lifecycle": "approved",
  "active": true,
  "certification": {
    "model_validated_on": "claude-4.6-sonnet",
    "tool_fingerprint": { "uv": "0.5.10", "mypy": "1.13.0", "pytest": "8.3.4" },
    "golden_set_ref": "evals/golden/repo-chore/bump-python-dep.jsonl",
    "last_recertified_at": "2026-07-30T15:22:11Z",
    "recert_status": "fresh"
  }
}
```

### 2.3 `SkillStats` (derived, T0)

Canonical form is JSON at `skills/<skill_id>/v<version>/stats.json`, validated against
[`schema/skill_stats.schema.json`](../../schema/skill_stats.schema.json). Never written directly;
always rebuilt from the run store. Losing this record is a rebuild, not a data-loss incident.

```json
{
  "skill_id": "bump-python-dep",
  "version": 3,
  "predictive_trust": { "applications": 14, "successes": 12,
                        "last_used_at": "2026-07-30T15:22:11Z" },
  "contribution": { "applications": 14, "successes": 12,
                    "suppressed_applications": 9, "suppressed_successes": 5,
                    "interval_low": 0.02, "interval_high": 0.38,
                    "last_evaluated_at": "2026-07-30T15:22:11Z" }
}
```

`predictive_trust.score` is not stored: it is derived on read,
`(successes + 1) / (applications + 2)`, so a single lucky application cannot mint a high-trust
skill (`0.8125` for the values above). Predictive trust is calibration, not a causal effect —
class-level retrieval lift lives on `RetrievalAblationEffect` (§19 / §24.2), and per-skill
retirement input lives on `contribution`.
`contribution.estimate` is derived:
`successes/applications − suppressed_successes/suppressed_applications`, or `null` when either
arm lacks observations — see §24.2 for when `null` is the only honest answer. A task-class
control baseline MUST NOT be subtracted here: selection into a particular skill is not random.

### 2.4 Field rules

- `certification_criteria` MUST contain at least one entry whose `kind` is not `judge`. A skill
  with only model-judged criteria MUST NOT reach `approved`.
- `steps[].loop.max_iterations` MUST be present when `loop` is present. Unbounded step
  loops are invalid.
- Step dependencies are derived exclusively from `steps[].input_bindings`. Each binding MUST
  name an existing predecessor step and an output that predecessor declares; the resulting graph
  MUST be a DAG. Free-floating ordering edges (`depends_on` as authoring input) are invalid —
  edges are data-carrying by construction (§26.1).
- `certification_criteria[].isolation` MUST be `fresh_context` for `judge` criteria (§26.3).
- `preconditions` are evaluated by `retrieve` **before** a candidate is offered to `plan`.
  A candidate failing any precondition MUST be dropped, not down-ranked. Allowed kinds are
  `file_exists`, `path_glob`, `env_present`, `tool_available`, and registered read-only `probe`
  entries — never arbitrary shell via a `command_succeeds` kind (§5).
- `parameters[].name` MUST match every `{{placeholder}}` used in `steps` and
  `certification_criteria`; unbound placeholders are a validation error at store time.
- Required certification criteria (`weight >= 1.0`) MUST carry a valid `sensitivity_proof` to
  count toward promotion; `preregistered` for this type means registered before the
  *certification runs* that validate it, not before the transcript that produced the draft — see
  the [ADR-0003 amendment](../adr/0003-criteria-preregistration.md#amendment-two-criteria-timelines-2026-07-30)
  (§15).
- `uses` entries MUST pin an exact child version, form an acyclic graph, and stay within
  depth 3 (§14).
- `SkillStatus.certification` MUST record the model and tool fingerprint validated against;
  drift in either marks the version `needs_recert` (§20).
- `SkillVersion.hygiene.secret_scan` MUST be `passed` before a version may be stored. This stays
  on the immutable version, not `SkillStatus`, because it is a one-time gate evaluated once,
  before the document is ever written.
- `provenance.curation` MUST be one of `human_authored`, `mined_from_human_artifact`, or
  `self_distilled`, and `self_distilled` versions require the higher evidence bar in §24.
- `SkillStats.contribution` is derived, never authored, and is the retirement input (§24).

### 2.5 Lifecycle values

`draft` → `candidate` → `shadow` → `approved` → `deprecated`, plus `benched`, `needs_recert`,
and terminal `quarantined`. All transitions are `SkillStatus` events, never edits to
`SkillVersion`.

| State | Retrievable | Notes |
| --- | --- | --- |
| `draft`, `candidate` | No | Awaiting validation or promotion |
| `shadow` | Comparison only | MUST NOT affect the caller's result |
| `approved` **and** in the active set | Yes | The only state eligible for direct application |
| `benched` | No (active retrieval) | Eligible for bounded offline shadow/exploration slots (§24.1); reversible |
| `needs_recert` | No | Until recertification passes |
| `deprecated`, `quarantined` | No | Terminal |

`benched` is distinct from both `deprecated` (superseded by a newer version) and `quarantined`
(suspected harmful). It means "not currently earning a retrievable slot", and returning to
`approved` requires no new version. Marking a version `quarantined` is **not** a task-plane
decision — no single run has the aggregate evidence (two consecutive field failures, or a recert
comparison) to make that call. It is a `SkillStatus` transition made by the Recertifier or
Curator (§20), reading across runs; see [ADR-0008](../adr/0008-optional-join-and-failure-signals.md).
