# Recertia Specifications: 5. Retrieval specification

## 5. Retrieval specification

Retrieval runs per memory plane and returns one `MemoryBundle` (§13.1). For the procedural
plane:

1. **Candidate generation** — union of vector top-`k` (default 20) over `intent` + `title`
   embeddings and lexical top-`k` over title, tags, and step tool names.
2. **Merge** — reciprocal rank fusion, `k=60`.
3. **Filter** — drop any candidate failing a `precondition` (including environment
   fingerprint mismatch), not in the **active set** (§24), in a lifecycle other than
   `approved`/`shadow`, or in a scope not readable by the task. Preconditions are
   `file_exists` / `path_glob` / `env_present` / `tool_available` / registered read-only
   `probe` checks with budget and evidence — retrieve MUST NOT spawn arbitrary shell
   (`command_succeeds` is not a precondition kind). Bounded shadow/exploration slots for
   `benched` or inactive `approved` versions (§24.1) are offline-only and MUST NOT enter
   this application candidate list.
4. **Rerank** — cross-encoder or model rerank of the top 10 against the task text.
5. **Score floor** — discard candidates below `min_score` (default 0.55). An empty
   candidate list is a valid and healthy outcome.
6. **Evidence and staleness demotion** — multiply score by (a) a low-evidence factor for
   skills below the `evidence_floor`, (b) a decay factor from time since last successful
   application and certification age (§21), and (c) a curation prior favouring
   `human_authored` and `mined_from_human_artifact` over `self_distilled` (§24).

Retrieval MUST NOT hard-drop a candidate for low trust or thin evidence — demotion only.
Hard trust cuts reproduce a measured failure mode in which aggressive exclusion performed
worse than having no library at all (`references.md` §1.2).
7. **Return** — at most 3 candidates with score, matched parameters, and precondition
   evidence attached.

Other planes: facts by hybrid search filtered to readable scope (max 10); cases by vector
similarity over task text (max 3 solved, max 3 dead ends); tool cautions by exact tool
match on the affordance plane.

Rules: when `arm == "control"` retrieval MUST return an empty bundle and record the
suppression (§19). Retrieval MUST be reproducible — the index snapshot id is recorded in the
run manifest, so any eval result ties to an exact memory state. Every bundle element MUST
carry `plane`, `provenance`, and `trust`, since the solver treats them as untrusted evidence
with differing weight (§22).

## 6. Validation specification

Criterion kinds and their contracts:

| Kind | Required fields | Pass condition |
| --- | --- | --- |
| `command` | `run`, `expect_exit` | Process exit code equals `expect_exit` |
| `assertion` | `expr` | Predicate over artifacts evaluates true |
| `schema` | `target`, `schema_ref` | Target validates against schema |
| `metric` | `metric`, `op`, `threshold` | Comparison holds |
| `judge` | `rubric`, `isolation`, `lens` | Model score ≥ 0.7 with recorded justification, evaluated in a fresh context |

Rules: criteria run in a sandbox with the run's workspace mounted; each has its own
timeout (default 300s) counted against `max_wall_clock_s`; a criterion that errors is a
**fail**, not a skip; output is captured (truncated to 32 KiB) and stored with the result.
Model-scored criteria additionally follow the isolation and triangulation rules in §26.3.

Required criteria MUST be locked at `intake` and MUST carry a sensitivity proof; criteria
lacking either property are advisory regardless of declared weight (§15).

## 7. Reusability filter

`distill` computes a `ReusabilityVerdict`. All checks MUST pass for `reusable`:

| Check | Rule |
| --- | --- |
| `parameterisable` | ≥1 extracted parameter, or `task_class` already seen ≥3 times |
| `context_free` | No step depends on a value unavailable outside the originating run |
| `checkable` | ≥1 non-`judge` criterion, and criteria actually executed this run |
| `not_duplicate` | Max cosine similarity to existing approved skills < 0.92, **or** route to `evolve` a new version of the nearest match |
| `bounded` | Every `loop` has `max_iterations` |

A `one_off` verdict is recorded against the task class. When one class accumulates ≥3
`one_off` records, the system MUST surface it for skill authoring — repeated near-misses
are the strongest available signal that a skill is missing.
