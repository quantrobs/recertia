# Loops, graphs, and what stays scarce (~2036)

**Status:** research note. Not contracts, not an ADR, not a remaining-work item.
It MUST NOT grow the task graph, rewrite the engine, enable HEX/compress, ship C5,
or move `a1` / `a2` / `a4` off their current statuses. Design impact, if any ever
arrives, is a commit to [`docs/references.md`](../docs/references.md) or an ADR —
the same rule as the preprint survey ([`README.md`](README.md)).

Written August 2026. Horizon: about ten years. The one-year deliverable remains
evidence, not more architecture
([`docs/architecture/one-year-roadmap.md`](../docs/architecture/one-year-roadmap.md)).

## Thesis

In ten years the scarce thing is still a **falsifiable loop**, not a larger graph.

A graph of loops is still loops. Topology is a representation of the *inner* walk
(one request, budgeted retries, auditable routes). Compounding — if it happens —
is an *outer* walk: durable versioned memory that the next request reads before
inventing anything, plus an offline plane that reorganises, practises, and
re-certifies what was learned. The decade's product catalogues will keep selling
the inner walk as if it were the outer one. That confusion is already old; it
will get louder as tools get cheaper.

Recertia's bet is that three loop levels remain load-bearing in 2036, that
industry "graphs supersede loops" commentary remains a category error, and that
the mechanisms which fail first are libraries, judges, and measurement — not
missing nodes.

## 1. Three shapes, none of which the decade retires

[ADR-0001](../docs/adr/0001-graph-with-loops.md) considered three implementation
shapes for a learning loop that is inherently cyclic:

1. Nested control flow inside a solver (retries as loops in a function).
2. A DAG pipeline runner, with re-invocation standing in for revision.
3. A cyclic state graph with typed state, conditional edges, and checkpoints.

Recertia took shape 3 and a thin in-house engine. That is a 2026 engineering
choice about **audit, resume, and replay**, not a prophecy that the field
converges on cyclic graphs.

All three shapes will still be in production in 2036:

- Nested solver loops get cheaper as observe–act and subagent tools improve.
  Recertia already treats the bounded scratch loop as a *solver property*; graph
  topology does not change to express it (roadmap P0-3).
- DAG re-invocation remains the default of every workflow product that forbade
  cycles on purpose. Revision will keep being "run the DAG again" for people
  whose state is not the audit record.
- Cyclic graphs remain the honest encoding of "try again, differently, with the
  same budget object." They do not automatically compound. They make the inner
  loop inspectable.

The decade will not pick a winner. It will keep renaming 1 and 2 as "agents" and
3 as "graph engineering," then claiming a phase change. Recertia already declined
the viral loop→graph compilations as bibliography
([`docs/references.md`](../docs/references.md) §9). Cite primaries, or cite
Kopadze for the execution *hygiene* claims that survived scrutiny (§1.7) — not
the timeline overlay.

## 2. Why "graphs supersede loops" is the wrong forecast

Kopadze's practitioner explainer named real execution problems: fake edges,
hidden edges, silent merges, context collapse, worker/verifier context sharing
([`docs/references.md`](../docs/references.md) §1.7, **[F, practitioner]**).
Those are graph *hygiene*. Recertia absorbed them as contracts: data-carrying
`input_bindings`, resource claims, merge audits, layered fan-in, `fresh_context`
judges.

The overlay — that graphs are what loops grow up into — was ignored. It fails
on three counts that will still fail in 2036:

1. **A graph of loops is still loops.** Fan-out, join, and back-edges are loop
   structure made explicit. Making them boxes and arrows does not move learning
   across requests.
2. **Scale is not a topology result.** The Bun-rewrite cost illustration in that
   same explainer (~50 workflows, up to 64 concurrent agents, ~$165k, human
   supervision throughout) is a *budget and approval* problem. More nodes do not
   pay it.
3. **The literature's bottleneck is the librarian, not the runtime.**
   SkillsBench: human-curated skills +16.2pp over no-skill, LLM-self-generated
   +0.0pp (Li et al., arXiv:2602.12670 **[B]**). Ratchet: holding the author
   fixed and varying only lifecycle management is what lifts held-out pass@1
   (arXiv:2605.22148 **[F]**). Lifecycle neglect is the field-wide finding.
   A sixteenth node does not curate a library.

If 2036 has a dominant runtime, it will be whichever one makes **criteria,
spend, and routes** reconstructible without re-running a model. That can be a
cyclic graph, a well-traced nested loop, or a DAG that finally stores deltas.
Recertia's engine is small *so that* `RunState` can be the audit record and the
replay format. ADR-0001's revisit condition still holds: if the engine's scope
grows past routing, persistence, and budgets, that is a signal to revisit the
decision — not to keep extending it. Remaining-work rule 3 is the operational
form: **do not grow the graph**
([`docs/architecture/remaining-work.md`](../docs/architecture/remaining-work.md)).
Fifteen nodes stay T3.

## 3. Three loop levels that should still exist

[`docs/architecture/overview.md`](../docs/architecture/overview.md) already
names the levels. The horizon claim is that they do not collapse into one
"agent runtime."

| Level | Lifetime | What it is for | What 2036 still needs |
| --- | --- | --- | --- |
| **Inner** | One request | Attempt → check → revise under a budget | Explicit routes, attempt isolation, no-progress detection, spend on every back-edge |
| **Outer** | Across requests | Memory written by one walk, read by the next | Versioned, reviewable, revertible stores; retrieval before invention; a floor on the active set |
| **Meta** | Offline, governed | Change *how* the system learns | Jobs that propose and cannot promote; a boundary the system may not rewrite (ADR-0004, ADR-0005) |

The inner loop will look more impressive. Models will plan longer, tools will
fan out further, "multi-agent graphs" will be the default screenshot. Most of
that is still one request. If the outer loop is missing, the system is a
competent agent with amnesia. If the meta loop is missing, it cannot reorganise,
practise the tail, or notice rot — and if the meta loop is *ungoverned*, it
optimises away the harness (lower the promotion bar, shrink the control arm,
score its own homework).

ADR-0005's governing rule does not age out: **the system may not modify the
mechanisms that measure or constrain it.** T3 includes graph topology, the
ablation rate, promotion thresholds, and the boundary itself. A 2036 product
that lets the runtime retune those surfaces will look more autonomous and will
be less able to say whether it improved.

## 4. What actually gets absorbed

Some 2026 machinery should become boring infrastructure. That is success, not
a reason to reopen topology.

**Trajectory as substrate, not as RL.** Yan et al. (arXiv:2607.01120 **[F]**)
diagnosed a missing decision-level event stream. Recertia took the diagnosis
and declined the weight-update loop (ADR-0011). By 2036, append-only
decision events and offline replay against a candidate world should be as
unremarkable as request logs. The fork that still matters: whether those
events train parameters or only support library hygiene and counterfactuals.
Recertia's bet is scaffolding-only remains the honest path until a harness
exists that reward-hacking cannot silently pass.

**Step-graph hygiene becomes Curator work.** Parallelise/serialise proposals
already act on `input_bindings` and claims from observed unused inputs and
merge failures — offline, golden-gated, not a new task-plane node. Fake-edge
rate and merge-gap rate are the numbers that say whether "we have a graph"
is doing any work
([`docs/architecture/measurement-and-scope.md`](../docs/architecture/measurement-and-scope.md)).
In ten years, a skill whose declared edges are habitual serialisation should
be as embarrassing as an untyped API.

**Observe–act stays inside `solve`.** Putting a scratch loop on the task graph
would confuse attempt isolation with tool iteration. The decade will keep
offering "just add a node." Recertia's answer stays: solver property, budgeted,
transcripted.

**Second domains test the shared layer, not a new graph.** If
`research-synthesis` needs structural change, that is a defect in contracts
and nodes that already exist. A third task class is still Phase 4+.

What does *not* get absorbed into infrastructure without evidence:

- Unbounded skill libraries (Ratchet Proposition 1: without finite cap `C` and
  threshold `τ` the performance floor collapses).
- Self-authored skills as a default quality source (SkillsBench; Miner prefers
  `mined_from_human_artifact`).
- Contribution retirement that includes `judge` criteria (Blind Curator,
  arXiv:2607.07436 **[B]**: false-pass bias silently disables the curator past
  a threshold more data cannot cross).
- Learned retrieval rankers and RL on the policy plane (deferred until the
  ablation arm and sensitivity proofs are trusted — and they are not, until
  real traffic says so).

## 5. Failure modes the decade will keep rediscovering

These are already named. 2036 will rediscover them under new product names.

| Failure | Why it survives | Recertia's present control |
| --- | --- | --- |
| Library drift | Growth looks like progress | Bounded active set, contribution retirement, `library_yield` |
| Harsh retirement | Pruning feels like hygiene | Evidence floor; A4 went *below* the no-skill baseline |
| Fake edges | Habit serialises for nothing | Bindings must carry data; unused bindings are Curator proposals |
| Hidden edges | Shared files/locks/APIs | Resource claims; overlapping write/exclusive forbids concurrency |
| Silent merges | A dead branch vanishes into a complete-looking result | Merge audits; fail decomposition joins on gaps |
| Context collapse | Raw fan-in exhausts the window | Layered fan-in; deterministic reduction where mechanical |
| Worker scores its own artifact | Agreement in a different font | `fresh_context` judges; producing instance may not score |
| False-pass judge | Symmetric noise is fine; one-sided bias is not | Non-`judge` contribution; planted-failure canary; `a4` still `untested` |
| Measurement capture | Locally rational T2/T3 writes | The system may not change the measurers |
| Inner loop sold as outer | Demos are single-request | Three planes; eval firewall; control arm |

A 10-year graph forecast that does not mention judges and libraries is a
runtime brochure.

## 6. What Recertia is betting will still be true

These are bets, not measurements. `a1` is `under evaluation`; `a4` is
`untested`. CI that reports `"not established"` correctly is not a 10-year
result.

1. **Machine-checkable domains can show lift from retrieval** — or they cannot,
   and that negative result is the design review, not a reason to add nodes.
   Negative `a1` **halts** Phase-3 scope expansion. It does not license HEX
   as consolation search.
2. **Representational improvement still has more headroom than parametric
   improvement** for this class of system: memory, retrieval, validators,
   policy — not weight training. Fine-tuning and policy RL stay deferred
   until correction data is plentiful and the harness is trusted.
3. **A small explicit graph beats a large implicit one** for replay. The
   engine stays thin so node outputs plus `RunState` reconstruct the walk.
4. **Plural memory stays plural.** Procedures, facts, cases, affordances, and
   policy do not collapse into one "skill store." Negative knowledge stays
   first-class.
5. **Offline jobs stay the only place whole-library work happens.** No job
   writes `approved`. The golden gate remains in front of promotion.
6. **Verifier isolation is necessary and not sufficient.** An isolated judge
   can still be false-pass-biased. The false-pass rate has to be a number
   attributed to `provider × model_version`, watched, not hoped.

## 7. What would falsify this note

Write these down so the note cannot hide behind poetry.

- Nested solver loops with first-class traces, budgets, and resume beat a
  cyclic graph on reconstructability *and* on operator cost to audit. Then
  ADR-0001's in-house engine is a local maximum, and the revisit clause
  fires — still without adding nodes first.
- Unbounded libraries with no retirement threshold compound on real
  `repo-chore` traffic. Then Ratchet's floor property failed to transfer, and
  ADR-0006 needs a design review.
- `a1` is `refuted` with a Wilson interval that excludes a positive lift.
  Then "outer loop via skills" is the thing that failed. HEX as recovery is
  a T2 experiment with a human note, not a topology change.
- A judge with no isolation and no non-`judge` contribution remains safe for
  retirement at production rates. Then Blind Curator did not transfer; keep
  the canary anyway.
- A system that may rewrite its promotion bar and ablation rate still produces
  trustworthy lift numbers. Then ADR-0005 is too strict — extraordinary
  claim, needs extraordinary traffic.

Until those measurements exist, this file is not evidence.

## 8. Explicit non-claims

- This note is not operator-mode GA. Tooling for backup, tabletop, and canary
  is shipped; four consecutive soak weeks and a filled tabletop log are ops.
- This note does not mark research assumptions `supported`.
- This note does not add a node, adopt an agent framework, or schedule an
  engine rewrite.
- This note does not enable `practice_hex_search` or `curator_compress`.
- This note does not write `docs/architecture/portfolio-measurement.md`.
- This note is not a second-party threat model and does not authorize C5.

The useful 10-year picture is not "loops become graphs." It is: **inner loops
get cheaper; outer loops stay hard; meta loops stay dangerous.** Recertia is
built to keep those three distinct. Whether managed memory compounds *here*
is still a number we do not have. That number, not a larger graph, is what
the next decade of this project is for.
