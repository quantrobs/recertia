# Trajectory events and counterfactual replay

Normative companion to [ADR-0011](../adr/0011-trajectory-and-counterfactual-replay.md).

## Trajectory events

- Contracts: `contracts/trajectory.py`
- Storage: `{runs_root}/trajectories/{run_id}.jsonl` (append-only) + optional `.meta.json`
- Emitter: `recertia.trajectory.emitter.TrajectoryEmitter` (pure)
- Writer: graph engine only

### Phase-1 required kinds on a completed run

`criteria_locked`, `retrieval_result`, `plan_choice` (when strategy/chosen set), `criterion_scored` (per result when validate ran), `terminal`.

Control-arm runs still emit `retrieval_result` with `suppressed=true`.

## Replay

- Contracts: `contracts/replay.py`
- Harness: `recertia.replay.harness.ReplayHarness`
- Modes:
  - `retrieval_only` — no solver calls; applies WorldState suppressions/overrides
  - `validate_only` — re-derive success from `criterion_scored` events; optional live `criterion_rescorer`
  - `full_execution` — opt-in via `RECERTIA_ALLOW_FULL_REPLAY=1` + budget; optional `orchestrator_factory` for isolated child graph

### Curator

Active-set mutations SHOULD attach a `ReplayPack` from retrieval-only counterfactuals over trajectories that referenced the skill (`sample_trajectories_for_skill` + `build_replay_pack`).

## Boundaries

- `recertia.nodes` MUST NOT import `recertia.replay`
- Trajectory failures MUST NOT fail the run (engine swallows emission errors)
- Trajectory = T0; replay = T1
