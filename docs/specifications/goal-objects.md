# Fandea Specifications: Goal objects (Variant B)

## 15.5 Goal objects

A `Goal` is the preferred primary input for a run. It is a structured declaration of desired
outcomes and hard constraints. Natural-language context is optional and never constitutes the
success contract by itself.

### 15.5.1 Presence

A `Task` MUST contain either a non-empty `Goal` or (during the compatibility window) a
non-empty `request`. New clients SHOULD supply a `Goal`.

### 15.5.2 Hard contract

A `Goal` MUST contain ≥1 `DesiredState` with `weight ≥ 1.0` and `kind ≠ "judge"`. A Goal that
contains only judge criteria is rejected at validation time.

### 15.5.3 Compilation

At `intake`, the `Goal` is compiled into `list[TaskCriterion]` by a pure function
(`contracts.goal.compile_goal`). The resulting set is locked exactly as specified in §15.1.
Compilation MUST be deterministic given the Goal and the environment fingerprint used for
sensitivity proofs.

| DesiredState.kind | Compiles to |
| --- | --- |
| `file_exists` | `command`: `test -f {path}` |
| `file_contains` | `command`: `grep -qE '{pattern}' {path}` |
| `command` / `assertion` / `schema` / `metric` / `judge` | direct field map |

| Constraint.kind | Behaviour |
| --- | --- |
| `must_pass_command` | required `command` criterion |
| `must_not_modify` | required criterion (snapshot / existence check) |
| `budget_ceiling` | folded into `Budget` — not a criterion |
| `no_external_effects` | tool-runtime policy flag — not a criterion |

### 15.5.4 Sensitivity proofs

Every required criterion produced by compilation MUST carry a valid sensitivity proof before
the lock is final. If proofs are missing, the critic MAY author them; criteria the critic
only proved retain their original `source` (typically `"caller"`).

### 15.5.5 Two timelines unchanged

Compiled `TaskCriterion` objects answer “did this run solve what the caller asked for?” They
NEVER become `SkillCertificationCriterion` objects. Skill certification remains post-hoc
relative to the originating transcript and pre-registered relative to certification runs
(ADR-0003 amendment).

### 15.5.6 Strategy hints

`Goal.strategy_hint` (`abstain` | `portfolio` | `decomposition`) is the preferred control
signal for plan. Plan MUST prefer `strategy_hint` over pattern-matching on `context` /
`request` text when both are present.

### 15.5.7 Source precedence (updated)

Caller-declared Goal (compiled) > task-class Goal template > critic refinement > (legacy)
critic-from-request.

### 15.5.8 Legacy path

A pure-`request` Task is accepted during the compatibility window. Silent critic lock from
prose without an explicit confirmation policy is deprecated for new clients.
