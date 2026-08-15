# Ten-year horizon: beyond prompts (exploration)

- **Status:** exploration — not an ADR, not a roadmap, not a merge gate
- **Date:** 2026-08-13
- **Horizon:** ~2036
- **Committed plan:** remains [`one-year-roadmap.md`](one-year-roadmap.md)
- **Narrowing instrument:** [`ten-year-horizon-narrowing.md`](ten-year-horizon-narrowing.md)
- **Objectives (worked run):** [`ten-year-horizon-objectives.md`](ten-year-horizon-objectives.md)
- **UX review:** [`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md)

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
(`a1`, `a2`, `a4`). The ten-year picture below assumes they can. §7 says what to believe
instead if they cannot.

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

## 4. The human interface, checked against the literature

Section 3 is architecture. This section asks the narrower question a reader should ask of
any "beyond prompts" claim: *what does a person actually look at and touch?* HCI has
forty years of evidence about what happens when an interface is words in, words out, and
this design should be checked against it rather than asserted against it. Citations follow
[`references.md`](../references.md)'s convention: **[F]** = fetched and read directly,
**[B]** = taken from a citing source's bibliography and not independently verified,
**[F, practitioner]** = non-academic source read directly, carrying argument rather than
measurement.

### 4.1 The prompt is a regression, not an advance

Shneiderman named *direct manipulation* — continuous representation of objects of interest,
rapid reversible actions, physical gestures instead of command syntax — as the property
that produced "glowing enthusiasm" instead of "grudging acceptance" (**Direct Manipulation:
A Step Beyond Programming Languages**, Shneiderman, *IEEE Computer*, 1983 **[F]**). A prompt
box is a step *back* toward the command-language interfaces that paper argued against: no
continuous representation of the object being changed, no way to see partial progress, and
recovery from a bad instruction means retyping, not undoing.

Hutchins, Hollan, and Norman formalized *why* command languages cost more: the **gulf of
execution** (translating a goal into system-legible actions) and the **gulf of evaluation**
(translating system state back into a judgement about the goal) (**Direct Manipulation
Interfaces**, *Human–Computer Interaction* 1(4), 1985 **[F]**). A chat window makes both
gulfs *linguistic* — the user must phrase the goal in words the model will parse well, then
re-read prose to judge whether it worked — instead of closing them with visible, manipulable
state.

**Design implication already taken:** a Goal's `DesiredState[]` is a continuous
representation of the object of interest — what the world should look like when this is
done — not a command. Criteria lock (ADR-0003) is the evaluation side closed *before*
execution starts: the user does not read prose afterward to judge success, the machine
checks it. The remaining gulf-of-evaluation surface is the walk itself, which is why Tower
exists as a graph view, not a scrollback.

### 4.2 Prompting has a name for its own failure, and it is not a skill issue

Zamfirescu-Pereira, Wong, Hartmann, and Yang studied non-AI-experts designing LLM prompts
and found they design *opportunistically* rather than systematically, and — the load-bearing
finding — that they default to treating a prompt as a **human-to-human instruction** rather
than a technical configuration, because the interface gives them no other vocabulary (**Why
Johnny Can't Prompt: How Non-AI Experts Try (and Fail) to Design LLM Prompts**, CHI 2023
**[B]**). This is not a training gap that better courses fix; it is what happens when the
only available input modality is prose addressed to something that answers in prose.

Subramonyam, Pondoc, Seifert, Agrawala, and Pea extend Norman's gulfs with a third,
LLM-specific one: the **gulf of envisioning**, the distance between a goal and a prompt that
successfully invokes it, decomposed into a *capability gap* (can this even be done?), an
*instruction gap* (how do I say it so the model does that?), and an *intentionality gap*
(what should I expect back, and how do I know it matches what I meant?) (**Bridging the Gulf
of Envisioning: Cognitive Challenges in Prompt-Based Interactions with LLMs**, CHI 2024,
arXiv:2309.14459 **[F]**).

**Design implication already taken, and one still open:**

- The capability gap is answered *before* the user writes anything: Goal compiles
  deterministically to `TaskCriterion[]` (ADR-0010), so "can this be checked" is a compiler
  error, not a guess.
- The intentionality gap is answered by construction: locked criteria mean the user does not
  have to predict the model's output and judge whether it matches an intention — the
  validator does that against a pre-declared contract.
- The **instruction gap survives** and is the honest remaining UI problem: writing a
  DesiredState that is both true to the goal and machine-checkable is still an authoring
  skill. Suggest/Compose proposing draft Goals from retrieved cases (§4.6 below) is the
  mitigation the roadmap already has; a decade-scale answer is a *library of DesiredState
  templates per task class*, reviewed the way skills are reviewed, so authoring narrows to
  editing a diff instead of writing from a blank page.

### 4.3 Autonomy is a negotiated interface property, not a backend flag

Horvitz argued that the interesting design space is not "direct manipulation versus agents"
but their coupling: an agent should add value beyond what direct manipulation already gets
for free, reason about uncertainty in the user's goal, time its interventions to the user's
attention, and — critically — give the user cheap ways to invoke, refine, dismiss, or
terminate automated action (**Principles of Mixed-Initiative User Interfaces**, CHI 1999
**[F]**). Amershi et al.'s 18 guidelines operationalize the same idea across the lifecycle:
*make clear what the system can do*, *make clear how well it can do it*, *support efficient
correction*, *notify users about changes*, and *provide global controls* recur across all
four interaction phases (**Guidelines for Human-AI Interaction**, CHI 2019 **[F]**).

Recertia's T0–T3 self-modification boundary (ADR-0005) is exactly a mixed-initiative
contract, but as written it is an internal enforcement mechanism, not a surfaced interface
property. A 2025 framework closes that gap directly: it defines agent autonomy as *the role
the user plays* — operator, collaborator, consultant, approver, observer — and argues
autonomy should be a deliberate, user-legible design choice orthogonal to model capability,
not an emergent property of how capable the model happens to be (**Levels of Autonomy for AI
Agents**, arXiv:2506.12469, 2025 **[F]**).

**Design implication, not yet taken:** T0–T3 already *is* a five-tier autonomy ladder
(autonomous / policy-gated / human-gated / never-autonomous, plus the T1 shadow-promotion
boundary that turns a former human-gate into an autonomous one once evidenced). The gap is
that it is legible to code and to a reviewer reading ADRs, not to an operator reading a
console. A decade-scale interface makes each task class's current tier **visible and
explained** next to the run — "this skill applies at T1 (auto-promote, zero-regression
gate); this Goal pack step requires T2 sign-off because it touches the retrieval
threshold" — rather than leaving tier as something you infer from source code.

### 4.4 Never show one opaque number

Lee and See's synthesis of trust-in-automation research names the three properties an
interface must support for a person to calibrate trust correctly: **calibration** (does the
displayed confidence match real performance?), **resolution** (does it discriminate
situations where the system will succeed from ones where it will not?), and **specificity**
(is the confidence broken down by the conditions it depends on, or reported as one global
number?) (**Trust in Automation: Designing for Appropriate Reliance**, *Human Factors*
46(1), 2004 **[F]**). Overtrust from an uncalibrated or non-specific number causes misuse;
undertrust from a system that hides its own resolution causes disuse — both are interface
failures, not just modeling failures.

These are properties of trust, not a mandate to render three widgets on every row.
Amershi et al. (2019 **[F]**) warn that over-disclosure is itself a failure mode: a list
of fifty skills needs a scannable primary. The house rule is **progressive disclosure**:
the list/summary shows **one honestly calibrated primary** (contribution or lift with
interval — or `"not established"` when the interval spans zero, never a rounded point
estimate, star, or composite that hides the interval), and the detail view discloses
calibration (lift trend by task class over time), resolution (does this skill's score
separate wins from losses on held-out probes), and specificity (per task class, per
model version — never one library-wide star rating). A single *opaque* trust score for
a skill is exactly the interface failure mode the trust literature predicts will be
misused. Showing three numbers on every list row is the complementary failure
([`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md) F1).

Recertia's own measurement discipline already refuses a single opaque confidence: skill
trust is contribution-scored per outcome, causal lift is reported with a Wilson interval and
an honest "not established," and evidence sits below a floor until enough certification
trials accumulate (ADR-0006, [`measurement-integrity.md`](measurement-integrity.md)). The
Lee & See framework is worth naming explicitly because it turns "show your evidence" from
this project's house style into a citable requirement for that progressive-disclosure
shape, not for display width.

### 4.5 Chat is linear; the work underneath it is not, and shouldn't pretend to be

Two UIST 2023 systems independently diagnosed the same problem from the artifact side:
Graphologue converts a linear LLM chat response into an interactive node-link diagram
because "LLMs like ChatGPT present significant limitations in supporting complex information
tasks due to the insufficient affordances of the text-based medium and linear conversational
structure" (**Graphologue: Exploring Large Language Model Responses with Interactive
Diagrams**, UIST 2023, arXiv:2305.11473 **[F]**); Sensecape adds a hierarchy view so users
can move between foraging and sensemaking instead of scrolling a transcript (**Sensecape:
Enabling Multilevel Exploration and Sensemaking with Large Language Models**, UIST 2023,
arXiv:2305.11483 **[F]**). Both are retrofits: they impose structure onto a system whose
underlying computation is a single linear generation.

Recertia does not need the retrofit, because the underlying computation was never linear.
The execution plane is already a graph with loops (ADR-0001) and the improvement plane is
already scheduled, non-conversational jobs (ADR-0004). The decade-scale implication is
narrow but real: **Tower's run view is the artifact Graphologue and Sensecape had to
synthesize after the fact, available for free because the runtime is graph-shaped by
construction.** The interface risk is the opposite one — flattening a walk *back* into a
chat-shaped log for the sake of familiarity, which would spend this advantage for nothing.

### 4.6 A Goal-authoring notation is a notation, and can be scored as one

Green and Petre's Cognitive Dimensions of Notations gives a vocabulary for evaluating any
artifact a person edits — not just visual programming languages — along axes like
**viscosity** (how much has to change to make one small edit), **closeness of mapping**
(does the notation read like the domain, not like implementation), **premature commitment**
(does the notation force a decision before the user has enough information), and
**secondary notation** (can the user attach meaning — layout, comments, rationale — the
system does not itself execute) (**Usability Analysis of Visual Programming Environments: A
'Cognitive Dimensions' Framework**, *J. Visual Languages & Computing* 7(2), 1996 **[F]**).

Applied to `Goal`/`DesiredState`/`Constraint` as a notation rather than a data model:

- **Premature commitment** is deliberately accepted at intake — criteria lock *is* a
  premature-commitment tradeoff, made on purpose because ADR-0003 values a stable success
  contract over mid-run negotiation. Goal packs (ADR-0014) exist specifically to lower this
  cost at the *program* level by deferring lock to each step rather than one mega-Goal.
- **Viscosity** is the open decade-scale question: how much of a locked Goal has to be
  re-authored, versus edited, when one DesiredState turns out to be wrong mid-walk. The
  current answer is "start a new run"; a gentler answer is closer to git — amend, don't
  retype — without weakening the lock's guarantee for the criteria that did not change.
- **Closeness of mapping** is the argument for DesiredState prose staying readable English
  describing outcomes ("the CLI's `--help` output lists the new flag") rather than becoming
  a query language only compiler authors can write.
- **Secondary notation** — a place for "why" that the compiler does not execute — is what
  keeps Goal authoring from degenerating into the same opaque-syntax problem prompts have;
  today that lives informally in `Task.request` as optional context (ADR-0010) and should
  stay a first-class, non-executable field rather than be squeezed out as legacy.

Programming-by-demonstration research reached a parallel conclusion from a different
direction: "if a user knows how to perform a task, that should be sufficient to create a
program to perform the task... instead of learning a [command] language" (**Watch What I
Do: Programming by Demonstration**, Cypher et al. (eds.), MIT Press, 1993 **[F]**; survey:
Myers & Ko, **End-User Programming**, ACM overview, 2006 **[F]**). The decade-scale reading
for Goal authoring is not "demonstrate a macro" — Recertia is not recording keystrokes — but
the same instinct applied one level up: the fastest way to author a DesiredState should be
picking the nearest retrieved case and editing its diff, not writing a fresh sentence
against a blank compiler. This is Suggest/Compose's job today; a decade from now it is the
default authoring path, not an assist feature bolted onto a text box.

### 4.7 Memory that a person can hold, not just query

Ink & Switch's practitioner argument for **malleable software** — systems users can reshape
with minimal friction instead of "prefabricated applications built by developers far away,"
via a gentle slope from consumer to co-creator, editable tools rather than fixed apps, and
communal creation — is not academic HCI, but it names the interface property this
architecture's memory plane already has by construction (**Malleable Software: Restoring
User Agency in a World of Locked-Down Apps**, Litt, Horowitz, van Hardenberg & Matthews, Ink
& Switch, 2025 **[F, practitioner]**). Skills, facts, cases, and policy are diffable,
versioned, revertible data (ADR-0002), which is the "editable, not appliance" property the
essay asks for, applied to an agent's competence instead of to a document.

The gentle-slope pattern is the missing half: the essay's examples (spreadsheets, HyperCard)
succeed because a novice can *use* the artifact with zero editing and *grow into* editing it
without switching tools. A decade-scale library browser should offer the same slope —
consuming a skill's outcomes requires nothing; disagreeing with one reviewer edit and having
it become a Correction Miner proposal is the next rung; authoring a DesiredState template
for a whole task class is the top rung — rather than a hard line between "user" and
"curator" roles.

### 4.8 Summary: what the literature adds that the architecture didn't already say

None of these papers change §3's claims. What they add is falsifiable design vocabulary for
the interface layer specifically, and two concrete gaps worth tracking alongside `a1`/`a2`/
`a4`:

- **Autonomy tiers are enforced but not yet legible at the decision** (§4.3) — a console
  gap, not an engineering gate. A detail-page badge does not close Norman's gulf of
  evaluation; the T2 approval interstitial is the surface that matters
  ([`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md) F3).
- **Trust display defaults to a single opaque number wherever a dashboard is sketched
  informally** (§4.4) — worth a house rule: any UI mock that shows one skill-quality
  number without a calibrated primary (interval or `"not established"`) is a design
  review finding, the same way an untiered mutable surface is (ADR-0005). Requiring
  calibration, resolution, and specificity as co-equal list figures is the complementary
  finding. Progressive disclosure (calibrated primary + detail breakdown) is the shape
  ([`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md) F1).

## 5. Horizon layers (not a second roadmap)

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

## 6. What dies, what does not

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
- A single opaque trust number per skill (§4.4) — the interface failure mode the trust
  literature predicts, not a shortcut this design should reach for. Progressive
  disclosure (calibrated primary + detail breakdown) is the house rule, not "always
  render three."

## 7. What would falsify this picture

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

## 8. What this document must not become

- An engineering gate, a staffing plan, or a reason to open a new milestone.
- A license to grow the graph, add HEX, auto-advance, or learned rankers before their
  enablement predicates fire.
- A reason to mark `a1` / `a2` / `a4` supported without real traffic.
- A substitute for four consecutive soak weeks.

The next honest step is still the one-year roadmap: operator-mode GA, then a defensible
answer — in our domain, with our harness — to "does it get better, and can you prove it?"

A reusable auditor prompt that turns this file into a supportable position and a
checkable objectives list is
[`ten-year-horizon-narrowing.md`](ten-year-horizon-narrowing.md). One worked run is
[`ten-year-horizon-objectives.md`](ten-year-horizon-objectives.md), fine-tuned against
[`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md). None of these is a
remaining-work milestone.

If that answer is yes, 2036 looks like Goals, libraries, and programs. If that answer is
no, 2036 looks like better chat, and this file was a clean miss.

## 9. References (human interface)

Grounding for §4 only. Filed in the repo's main bibliography as
[`references.md` §10](../references.md#10-human-interface-design-for-post-prompt-systems)
(new category); reproduced here for convenience. Verification status per
[`references.md`](../references.md)'s convention: **[F]** fetched and read, **[B]** from a
citing paper's bibliography and not independently verified, **[F, practitioner]**
non-academic, read directly.

| Ref | Citation | Status |
| --- | --- | --- |
| Shneiderman 1983 | Shneiderman, B. *Direct Manipulation: A Step Beyond Programming Languages.* IEEE Computer 16(8), 1983. | **[F]** |
| Hutchins, Hollan & Norman 1985 | Hutchins, E., Hollan, J., & Norman, D. *Direct Manipulation Interfaces.* Human–Computer Interaction 1(4), 311–338, 1985. | **[F]** |
| Zamfirescu-Pereira et al. 2023 | Zamfirescu-Pereira, J.D., Wong, R.Y., Hartmann, B., & Yang, Q. *Why Johnny Can't Prompt: How Non-AI Experts Try (and Fail) to Design LLM Prompts.* CHI 2023. | **[B]** |
| Subramonyam et al. 2024 | Subramonyam, H., Pondoc, C., Seifert, C., Agrawala, M., & Pea, R. *Bridging the Gulf of Envisioning: Cognitive Challenges in Prompt-Based Interactions with LLMs.* CHI 2024, arXiv:2309.14459. | **[F]** |
| Horvitz 1999 | Horvitz, E. *Principles of Mixed-Initiative User Interfaces.* CHI 1999, 159–166. | **[F]** |
| Amershi et al. 2019 | Amershi, S., Weld, D., Vorvoreanu, M., et al. *Guidelines for Human-AI Interaction.* CHI 2019. | **[F]** |
| Levels of Autonomy 2025 | *Levels of Autonomy for AI Agents.* arXiv:2506.12469, 2025. | **[F]** |
| Lee & See 2004 | Lee, J.D., & See, K.A. *Trust in Automation: Designing for Appropriate Reliance.* Human Factors 46(1), 50–80, 2004. | **[F]** |
| Jiang et al. 2023 | Jiang, P., Rayan, J., Dow, S.P., & Xia, H. *Graphologue: Exploring Large Language Model Responses with Interactive Diagrams.* UIST 2023, arXiv:2305.11473. | **[F]** |
| Suh et al. 2023 | Suh, S., Min, B., Palani, S., & Xia, H. *Sensecape: Enabling Multilevel Exploration and Sensemaking with Large Language Models.* UIST 2023, arXiv:2305.11483. | **[F]** |
| Green & Petre 1996 | Green, T.R.G., & Petre, M. *Usability Analysis of Visual Programming Environments: A 'Cognitive Dimensions' Framework.* J. Visual Languages & Computing 7(2), 131–174, 1996. | **[F]** |
| Cypher et al. 1993 | Cypher, A. (ed.), with Halbert, D.C., Kurlander, D., Lieberman, H., Maulsby, D., Myers, B.A., & Turransky, A. *Watch What I Do: Programming by Demonstration.* MIT Press, 1993. | **[F]** |
| Myers & Ko 2006 | Myers, B.A., & Ko, A.J. *End-User Programming.* Invited research overview, 2006. | **[F]** |
| Litt et al. 2025 | Litt, G., Horowitz, J., van Hardenberg, P., & Matthews, T. *Malleable Software: Restoring User Agency in a World of Locked-Down Apps.* Ink & Switch, 2025. | **[F, practitioner]** |
