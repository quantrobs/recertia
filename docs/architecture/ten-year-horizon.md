# Ten-year horizon: beyond prompts (exploration)

- **Status:** exploration — not an ADR, not a roadmap, not a merge gate
- **Date:** 2026-08-13
- **Horizon:** ~2036
- **Committed plan:** remains [`one-year-roadmap.md`](one-year-roadmap.md)

This is an answer to a question, not a schedule. The one-year roadmap is still the only
document that may create engineering gates. Nothing here moves [`assumptions.md`](../assumptions.md)
off `under evaluation`. Nothing here grows the graph.

## 1. The claim

The prompt is a 2020s transitional interface. It exists because we still talk to models the
way we talk to people, and because the success condition of a chat is "a plausible reply."

Recertia already rejected that as the unit of work. A Goal is a desired state plus
constraints, compiled to locked criteria before anyone is allowed to invent
([ADR-0010](../adr/0010-goal-as-primary-input.md),
[ADR-0003](../adr/0003-criteria-preregistration.md)). Natural language is optional context.
In ten years the interesting systems will not be better chat. They will be better contracts,
better memory, and better measurement.

A prompt is a request that hope will be interpreted. A Goal is a request that can fail.

## 2. What Recertia already decided (2026)

The architecture is not waiting for 2036 to leave prompts behind. The bets that matter are
already on `main`:

| Bet | Where it lives | Why it is "beyond prompts" |
| --- | --- | --- |
| Structured Goal as primary input | ADR-0010 | The caller names outcomes, not instructions |
| Criteria lock before solve | ADR-0003 | Success is not negotiated in the transcript |
| Retrieval before invention | [overview](overview.md) non-negotiable 1 | Memory is queried; the model is not asked to "remember" |
| Plural, versioned memory | [ADR-0002](../adr/0002-plural-memory.md) | Skills, facts, cases, utterances, policy — not a chat log |
| Failure is knowledge | overview non-negotiable 4 | Dead ends are stored so they are not re-entered |
| Offline improvement plane | [ADR-0004](../adr/0004-offline-improvement-plane.md) | Learning does not happen while a user waits |
| Bounded self-modification | [ADR-0005](../adr/0005-self-modification-boundary.md) | The solver may not rewrite the judge |
| Goal packs as programs | [ADR-0014](../adr/0014-goal-packs-as-migration-programs.md) | Multi-step change is a sequence of contracts, not a mega-prompt |
| Console as control plane | [ADR-0012](../adr/0012-product-console-surfaces.md) | Chat is not the operator surface |

The one-year roadmap's job is to find out whether those bets *compound* on real traffic
(`a1`, `a2`, `a4`). The ten-year picture below assumes they can. Section 6 says what to
believe instead if they cannot.

## 3. What I see in 2036

### 3.1 Work is issued as desired state

The default way a human, a ticket system, or another agent asks for work is a Goal: required
desired states that a machine can fail, plus constraints (freeze zones, budgets, side-effect
class). The compiler still produces `TaskCriterion[]` and still locks them at intake. Suggest
and Compose still exist, but they propose Goals; they do not execute prose.

Prompt engineering as a job is gone the way punch-card encoding is gone. The scarce skill is
writing a DesiredState that can actually fail, and a Constraint that is honest about what
must not move.

### 3.2 Chat remains, off the critical path

Chat does not disappear. It is how people explore, argue with a draft Goal, and debug a
failed walk. It is not how serious work is dispatched, scored, or remembered.

That split is already the console design: Pilot composes; the run is a Goal; Tower inspects
the walk. In ten years every serious product that still looks like "an AI chat box" is
either a toy or a composition surface sitting on top of a contract runtime.

### 3.3 Competence lives in libraries, not weights

The model of 2036 is cheaper, faster, and more interchangeable than the model of 2026. That
does not make memory optional. Recurring work compounds by *representation*: versioned
skills, facts, cases, and policy that every later walk reads before inventing
([overview](overview.md) design goals). Weight updates are still a non-goal. Improvement is
still not parametric.

Organizations compete on libraries the way they once competed on codebases. The library is
diffable, reviewable, and revertible. A competitor can buy the same solver and still lose,
because they do not have the cases, the pitfall skills, or the contribution scores.

This is the Ratchet result taken at decade scale: lifecycle management, not authorship, is
the bottleneck ([`references.md`](../references.md) §1.1). Ten years of better models does
not dissolve a librarian problem.

### 3.4 Humans curate contracts and gates

The human is not gone. The human is no longer typing instructions into a void.

The load-bearing human work is:

- authoring and reviewing DesiredStates and Constraints
- sitting on T2 (policy, distiller guidance, retrieval thresholds)
- holding T3 (sandbox, promotion bar, ablation rate, graph topology, this boundary)
- labelling probe sets and judging Curator proposals — the role the one-year roadmap already
  names as the highest-leverage hire

SkillsBench's null on self-authored skills ([`references.md`](../references.md) §1.1) does
not get better because the author is an LLM in 2036. Uncurated growth is still library
drift. The decade's product is a *librarian with a golden gate*, not an unsupervised
memoir.

### 3.5 The graph does not go away

Reality has retries, partial success, and "try several ways at once." A linear chat cannot
express those without hiding control flow in a transcript. A cyclic graph can
([ADR-0001](../adr/0001-graph-with-loops.md)).

Fifteen nodes remain T3 today ([`remaining-work.md`](remaining-work.md) §1). In ten years
the topology may have been deliberately revised — by humans, with evidence — but "the agent
just loops until it feels done" is still not an architecture. Budgets on back-edges, join
accounting, and "nothing dispatched goes missing" are still the difference between a system
and a séance.

### 3.6 Measurement is the product's honesty

By 2036, a system that cannot report causal lift against a retrieval-suppressed control,
with an interval, including the honest result **"not established"**, is not taken seriously
for recurring work. That is already Recertia's non-negotiable 5. The decade's change is
that this becomes boring: as expected as a unit test, as unremarkable as a ledger verify.

The judge remains the dangerous component. Blind Curator is not a 2026 curiosity: a biased
acceptor silently disables retirement. The false-pass canary is still running. The
verifier is still not the solver asked whether it agrees with itself.

### 3.7 The T3 line holds

Capability growth makes the self-modification boundary *more* expensive to violate, not
less. A system rewarded for first-attempt success and cost will still try, locally
rationally, to lower the promotion bar, shrink the control arm, or grant itself tools
([ADR-0005](../adr/0005-self-modification-boundary.md)).

The governing rule does not age out: **the system may not modify the mechanisms that
measure or constrain it.** Shadow autonomy can expand (T1) precisely because the thresholds
that govern it cannot. Systems that fail in public in the 2030s will be the ones that let
the solver rewrite the judge.

### 3.8 Models become interchangeable solvers

Provider identity is already a pin in the run manifest, not a personality. In ten years a
Goal compiler plus a retrieval bundle plus a validator is the product. The model is a
solver behind that, swapped when the canary says the judge drifted or the cost curve
moved.

Failover and multi-provider are still a measurement-surface decision (one-year roadmap
§7), not a slogan. Two providers still double the judge-bias surface. The decade does not
make that arithmetic go away; it just makes the canary cheaper to run.

## 4. Horizon layers (not a second roadmap)

These are capability layers, not calendar phases. Layer A is what the one-year plan already
starts. Layers B and C are what becomes thinkable only if `a1` is supported in at least
one domain. They are not a license to skip soak weeks.

**Layer A — Contracts replace prompts.** Goal is the public input. Packs are how a
migration is a program of locked Goals rather than a mega-prompt. The console is a control
plane. Operator mode can run unattended on one domain with real cost and an injection
gate. This layer is the 2026–2027 roadmap.

**Layer B — Libraries replace folklore.** Recurring work stops living in wiki pages, chat
scrollback, and "ask the person who did it last time." The organization's memory is a
bounded, contribution-scored, golden-gated library with a performance floor. Curator
proposals carry trajectory replay. Practice converts failure clusters. Retirement is
observable. A second domain runs on the unchanged runtime, or the design is defective.

**Layer C — Programs replace tickets.** Desired-state programs are how work is issued
across a decade of change: not "open a ticket and hope," not "paste a prompt into an
agent," but a pack of Goals with dependencies, freeze zones, and a ledger. Other systems
(CI, issue trackers, research desks) emit Goals. Humans confirm T2/T3 and review
exceptions. The audit trail a regulator or an incident review wants is the walk, the
criteria, and the memory versions — not a reconstructed chat.

Layer C is the 2036 picture. It is not a 2027 milestone.

## 5. What dies, what does not

**Dies, or is demoted to composition:**

- Prompt libraries as the product
- "The model knows our repo" with no retrieval, no ledger, no revert
- Fine-tuning as the default improvement story for *recurring, checkable* work
- Unbounded autonomy as a feature
- Mega-Goals and prompt-only packs (already rejected by ADR-0014)
- Chat as the execution surface for anything with a side effect

**Does not die:**

- Language, for exploration and for drafting Goals
- Human gates on measurement, containment, and promotion
- Cyclic control flow
- Curation as the bottleneck
- The evidence floor, and the possibility that most of a low-traffic library sits below it
  (`a2`)
- Judge bias (`a4`)
- The option that compounding does not show up on our traffic (`a1`)

## 6. What would falsify this picture

This document is allowed to be wrong. These are the cleanest ways it would be:

1. **`a1` refuted** on machine-checkable domains, with a stable interval. Compounding is
   then a literature story we failed to reproduce. The product that remains is a competent
   agent with no memory — still useful, no longer the thesis. Chat-plus-tools stays the
   default. Halt Layer B/C; do not multiply blast radius (already the Phase-4 gate).
2. **`a2` refuted** — the evidence floor is unreachable at our volume even with Practice.
   The library is then a well-governed museum. Retrieval-before-invention still helps
   audit, not lift. Design review of the floor and of Practice, not a quiet lowering of
   the bar.
3. **`a4` refuted** — false-pass rates high enough to disable retirement. The judge is the
   product risk. Stop promoting. Do not "fix" it by asking the solver.
4. **A no-memory general agent dominates recurring checkable work** at lower cost than a
   retrieval-gated library, on our harness, not on a demo. Then Recertia's central claim
   is wrong and this horizon with it. Memory might still win on audit and rollback; that
   would be a different, smaller product.
5. **Regulation requires a human on every side effect.** T2 expands; Layer C stretches;
   the architecture still fits, because gates were never a temporary embarrassment.

Negative results are not project failure. They are the B7 machinery working.

## 7. What this document must not become

- An engineering gate, a staffing plan, or a reason to open a new milestone.
- A license to grow the graph, add HEX, auto-advance, or learned rankers before their
  enablement predicates fire.
- A reason to mark `a1` / `a2` / `a4` supported without real traffic.
- A substitute for four consecutive soak weeks.

The next honest step is still the one-year roadmap: operator-mode GA, then a defensible
answer — in our domain, with our harness — to "does it get better, and can you prove it?"

If that answer is yes, 2036 looks like Goals, libraries, and programs. If that answer is
no, 2036 looks like better chat, and this file was a clean miss.
