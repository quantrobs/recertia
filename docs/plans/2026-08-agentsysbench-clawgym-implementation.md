# Technical plan: AgentSysBench + ClawGym II, Recertia-shaped

- **Status:** proposed (review-adjusted 2026-08-22)
- **ADR:** [ADR-0018](../adr/0018-idle-state-offloading.md) (Phase 1.2)
- **Related:** [ADR-0002](../adr/0002-plural-memory.md), [ADR-0004](../adr/0004-offline-improvement-plane.md), [ADR-0005](../adr/0005-self-modification-boundary.md), [ADR-0011](../adr/0011-trajectory-and-counterfactual-replay.md), [ADR-0013](../adr/0013-openai-compat-gateways.md), [ADR-0015](../adr/0015-improvement-plane-search.md)
- **Papers:** Chang et al. AgentSysBench [arXiv:2608.15127](https://arxiv.org/abs/2608.15127); Song et al. ClawGym II [arXiv:2608.16798](https://arxiv.org/abs/2608.16798)

This is the corrected plan. The draft treated Recertia as if it held 28 GB live sandboxes and as if trajectory capture and an improvement plane did not already exist. Both are false. What follows is the same intent, aimed at the code that is actually here.

## Review of the draft (what changed)

| Draft | Problem | Adjustment |
| --- | --- | --- |
| Offload episodic / procedural / trajectory stores | Those stores are already durable SQLite/JSONL. Recertia containers are `--rm` + 512 MiB, one command. The 4.6× AgentSysBench win is *sandbox working-set hold*, which Recertia does not currently do. | ADR-0018 targets workdirs, snapshots, cold index pages, large checkpoint blobs. Default **off** until Phase 0 measures our RSS. |
| `solver/tools.py`, `nodes/retrieve.py` cache | `solver/tools.py` is a stub. Tools live in `solver/registry.py`. Retrieve has no cache today (T0 is allowed). | Read-only tool-result cache in registry/runtime; retrieval cache in `retrieval/`. Invalidate on snapshot hash and skill promotion. |
| New serving proxy for model-call capture | [ADR-0011](../adr/0011-trajectory-and-counterfactual-replay.md) lists multi-tenant proxies out of scope. [ADR-0013](../adr/0013-openai-compat-gateways.md) is URL-compat, not a capture plane. `ModelClient.complete` and `solver/transcript.py` already see every call. | Capture at `ModelClient.complete` → trajectory events. No new HTTP proxy. |
| "Strengthen trajectory/emitter.py" as green field | Trajectory JSONL + engine emission + three replay modes already shipped. | Prefix-tree is a **derived view** over existing events, plus dead-leaf pruning. Do not fork a second stream. |
| Phase 4 black-box RL / mix-harness / PPO | Recertia does not update weights. The system may not modify the mechanisms that measure it ([ADR-0005](../adr/0005-self-modification-boundary.md)). | Phase 4 = offline job that emits **skill or policy proposals only**, gated by golden + control-arm lift. Outcome distillation first. No PPO, no GRPO, no mix-harness training of a foundation model. |
| Task-aware budgeting in `jobs/workers.py` | Budgets, `JobQuota`, and version-write cap ([ADR-0017](../adr/0017-version-write-budget.md)) already exist. A parallel budget is a lie. | Stretch only, and only as routing *hints* inside existing `Budget` / `JobQuota`. |
| "≥ 3–4× memory reduction" as a success metric now | Unmeasured. Recertia's peak may already be the 512 MiB cgroup plus host workdirs. | Phase 0 baselines RSS. Targets become numbers against *that* baseline. |
| Six properties unnamed | Phase 0 cannot be tested. | Named below. |
| Idle as a graph state mixed with nodes | Fifteen nodes are T3 ([ADR-0015](../adr/0015-improvement-plane-search.md)). | Watcher on the run worker, not a sixteenth node. |
| Causal lift after each phase | `recertia lift` just gained variance-aware reporting. Practice must not contaminate user-facing metrics ([ADR-0004](../adr/0004-offline-improvement-plane.md)). | Use existing lift harness; exclude Practice; no new lift path. |

## Goals

- Reduce **working-set** memory and redundant tool/retrieval work on long-running and concurrent Recertia sessions, without touching the three planes or "only keep what still works."
- Make the Improvement plane able to consume reconstructable black-box trajectories as **proposal input**, without violating harness opacity or [ADR-0005](../adr/0005-self-modification-boundary.md).
- Make AgentSysBench's six properties measurable inside Recertia so later phases are data-driven.
- Every landing change must demonstrate, or at least not regress, control-arm lift on golden evals via `recertia lift`.

## The six properties (Phase 0 must emit all six)

From AgentSysBench, mapped to Recertia surfaces:

1. **Heavyweight stateful execution** — non-LLM vs LLM latency share; peak RSS (process + workdir bytes). Recertia expect: non-LLM (retrieve, validate, container, judge) already dominates many hops.
2. **Heterogeneous resource affinity** — GPU inference vs memory-bound retrieve vs CPU sandbox. Recertia: model client vs `retrieval/` vs `solver/container.py`.
3. **Shifting bottlenecks** — per-node `node.finished` latency histograms, not a single "the" bottleneck.
4. **Idle-but-live intervals** — time between hops with no tool subprocess; currently unlabelled.
5. **Control-plane tax** — tokens/latency in judge, context, review vs productive `solve`. Recertia already forbids judge/solver shared context; we still do not *meter* the tax as a first-class ratio.
6. **Cross-request tool/retrieval redundancy** — exact-match repeats of read-only tool args and retrieve queries.

## Success metrics (set after Phase 0, not before)

- Peak / average RSS and workdir bytes on idle-heavy fixtures. *Target only after baseline.* Do not import 4.6×.
- Tool / retrieval redundancy rate on golden classes (exact-match repeats / all calls). Draft 20 % was a search-QA number; ours may differ.
- `idle.restore` latency < 5 % of median hop time, excluded from task-class latency.
- Trajectory prefix-tree reconstructability rate (events → tree → events, hash-stable).
- Causal lift on golden task classes after each landing phase: no regression; Practice excluded.

## Risks and guardrails

- **Restore latency polluting lift** → named `idle.restore` span; lift code ignores it.
- **Cache serving stale tool results into a mutated workdir** → cache key includes workspace snapshot hash; write/exclusive tools never cached; TTL plus invalidation on promotion and snapshot.
- **RL instability / self-modification** → no weight writes, ever, from this plan. Proposals only. Same golden gate + control-arm as Curator.
- **Sixteenth node** → watcher in `workers/run_worker.py` / engine idle hook. Feature flags cannot grow `contracts.graph.NODES`.
- **Offload-by-default hiding a bug** → `idle_offload_enabled` defaults false.
- **Measuring Practice as product lift** → Practice runs stay out of user-facing metrics.

## Phased implementation

### Phase 0 — Grounding and instrumentation (1–2 days)

Must ship before any cache or offload is enabled.

1. Add both papers to `docs/references.md` with **[F]** and a short applicability mapping (sandbox-hold ≠ Recertia `--rm` container; ClawGym II PPO ≠ Recertia proposals). Follow the Ye/Zhao 2026-08-22 pattern.
2. List ADR-0018 in `scripts/generate_architecture2.py` and regenerate `docs/architecture2.md`.
3. Extend `src/recertia/telemetry.py` + hop accounting in `src/recertia/graph/engine.py`:
   - component class on `node.finished`: `llm | retrieve | validate | container | control_plane | other`
   - `rss_bytes` / `workdir_bytes` gauges
   - `tool.invoked` canonical key (name + normalised args hash) so redundancy is countable
   - `control_plane_token_tax` (judge/context/review vs solve)
4. Baseline the six properties on 2–3 golden task classes. Write the numbers into the tracking issues. No Phase 1 enablement without this table.
5. Open tracking issues under labels **Systems efficiency** and **Black-box improvement**.

**Tests:** telemetry unit tests that a golden hop emits the new attributes; a fixture that repeats a read-only tool and shows redundancy_rate > 0.

**Done when:** a checked-in baseline table exists; `idle_offload_enabled` still false.

### Phase 1 — Quick systems wins (Paper 1) — highest ROI (1–2 weeks)

#### 1.1 Read-only tool-result / retrieval cache

- **Files:** `src/recertia/solver/registry.py`, `src/recertia/solver/runtime.py`, `src/recertia/retrieval/pipeline.py` (not `solver/tools.py`). Optional T0 sidecar: `src/recertia/memory/affordance/` if the hit is "this tool, these args, this snapshot → this observation."
- **Key:** `(tool_name, canonical_args_hash, workspace_snapshot_hash)`.
- **Eligibility:** tools whose side-effect class is read; `require_tool_approval_for_non_read` already exists. Writes never cache.
- **Invalidation:** snapshot change, skill promotion, explicit TTL (short).
- **Log:** `cache.hit` / `cache.miss` on telemetry.
- **Tests:** hit on exact repeat; miss after workdir mutation; write-tool never stored; promotion flushes retrieve cache.
- **Done when:** redundancy_rate drops on the Phase 0 fixture without lift regression.

#### 1.2 Idle-state offloading (ADR-0018)

Implement the ADR. Default off. Enable on a soak fixture only after Phase 0 numbers exist.

- **Files:** `src/recertia/graph/engine.py`, `src/recertia/graph/store.py`, `src/recertia/workspace/snapshot.py`, `src/recertia/workers/run_worker.py`, `src/recertia/retrieval/index.py`, `policy/default.json` (`state_management`), `src/recertia/governance/tiers.py` (no new untiered module).
- **Tests:** hash-stable pack/restore; resume after forced idle; RSS/workdir delta; lift non-regression with offload on.
- **Done when:** an idle-heavy fixture shows a measured RSS drop *and* resume still satisfies criteria.

#### 1.3 Task-aware routing (stretch, after 1.1–1.2)

Do **not** add a second budget. If Phase 0 shows 32×-class hop divergence, add routing *hints* that reuse `Budget` and `JobQuota` (`src/recertia/jobs/workers.py`, graph hop scheduler). No new cap dimension.

### Phase 2 — Trajectory readiness for black-box improvement (Paper 2 foundation) (1–2 weeks)

ClawGym II's usable pieces: sandbox isolation, capture at the model boundary, prefix-tree reconstruction. Not usable: PPO/GRPO on a foundation model.

- **Capture:** every `ModelClient.complete` emits a trajectory event (engine already owns emission; [ADR-0011](../adr/0011-trajectory-and-counterfactual-replay.md)). `solver/transcript.py` "model" events are a source, not a parallel store.
- **Prefix tree:** derived index over a run's trajectory JSONL (`src/recertia/trajectory/`). Node = model call; retries are siblings. Dead-leaf / over-branching pruning is a view, recorded as telemetry, not a destructive edit of the JSONL.
- **Reconstructability:** tree → event seq hashes equal to the original for kept leaves.
- **Replay:** keep `retrieval_only` / `validate_only` / `full_execution`. Prefix-tree pruning must not break `validate_only`.
- **Tests:** synthetic branching transcript → stable tree; prune dead leaf → reconstructability on remaining; engine still cannot import replay from `recertia.nodes`.

**Done when:** reconstructability rate is reported on golden runs; no second event stream exists.

### Phase 3 — Concurrent sandboxed rollouts (1 week)

Recertia already has an OCI backend and a soak harness (`src/recertia/ops/soak.py`). This phase is **Practice density**, not a new sandbox.

- Scale isolated Practice jobs under existing `JobQuota` ([ADR-0015](../adr/0015-improvement-plane-search.md)).
- Each job: own workdir, own container invocations, own trajectory file.
- If we introduce long-lived containers here, they **must** implement ADR-0018 (pause/offload) rather than hold RAM. Otherwise we import AgentSysBench's 28 GB problem on purpose.
- **Tests:** N concurrent Practice jobs, isolation (no cross-workdir writes), soak density, lift still excludes Practice.

**Done when:** soak can run N>1 isolated Practice jobs without RSS growing linearly with *idle* jobs (offload on).

### Phase 4 — Black-box improvement loop (2–4 weeks, gated)

New or extended **offline job** on the Improvement plane ([ADR-0004](../adr/0004-offline-improvement-plane.md)):

1. Read captured trajectories (Phase 2 trees).
2. Roll out candidates in the sandbox (Phase 3).
3. Produce **skill or policy proposals only**.
4. Same validation, golden-set regression, control-arm lift, review path as Curator. Promote nothing itself.

Start narrow (one skill family). "Mix-harness joint optimisation" is a later research question, not a deliverable. Outcome distillation only. HEX stays default-off until a lift interval exists (current policy).

**Hard non-goals for Phase 4**

- No weight updates, LoRA, PPO, GRPO, or training-inference split.
- No serving proxy in front of `OpenAIModelClient`.
- No graph topology change.
- No writing approved state, distiller guidance, promotion thresholds, or ablation rate from the new job (T2/T3 stay T2/T3).

**Done when:** a single-family job emits a proposal that can pass or fail the existing gate; a failing proposal does not land; golden lift does not regress.

## Build order and stop conditions

```
Phase 0 baseline  ──►  1.1 cache  ──►  1.2 offload (still default off)
                              └──►  1.3 only if Phase 0 shows hop divergence
Phase 2 trees     ──►  Phase 3 density  ──►  Phase 4 proposals
```

Stop and rewrite if:

- Phase 0 shows RSS is already cgroup-capped and idle holding is negligible → drop 1.2 from the critical path; keep the lifecycle flag for Phase 3.
- Cache hits are ~0 on golden classes (no redundancy) → do not ship a cache to look busy.
- Prefix-tree reconstructability < 99 % on golden → do not start Phase 4.

## Tracking

- Issues: `systems-efficiency` (Phases 0–1, 3), `black-box-improvement` (Phases 2, 4).
- Policy: `state_management.idle_offload_enabled` defaults false on `policy/default.json`.
- Lift: `recertia lift --task-class <golden>` after every landing PR; Practice excluded.
