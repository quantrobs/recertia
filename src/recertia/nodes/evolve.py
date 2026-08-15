"""``evolve``: restore workspace and apply a class-specific repair move (specs §16, M2).

Consults episodic dead ends to avoid repeating a failed approach, and short-circuits when
the last two result vectors are identical (no progress).
"""

from __future__ import annotations

from contracts.run import RunState
from recertia.nodes.context import NodeContext, NodeOutcome


def evolve(state: RunState, ctx: NodeContext) -> NodeOutcome:
    if not state.workspace_snapshots:
        raise ValueError("evolve requires a clean workspace snapshot on the run state")

    # Short-circuit: identical result vectors ⇒ no progress (route table also checks this,
    # but evolve records the reason so the route log shows why we still re-dispatch).
    if len(state.results_history) >= 2 and state.results_history[-1] == state.results_history[-2]:
        # Still restore and re-dispatch; classify_failure's route predicate will send the
        # *next* failure to record_dead_end. We annotate so tests can see the signal.
        note_prefix = "no_progress:identical_results; "
    else:
        note_prefix = ""

    clean_ref = state.workspace_snapshots[0].snapshot_ref
    ctx.workspaces.restore(ctx.workdir, clean_ref)
    snapshots = list(state.workspace_snapshots)
    snapshots[0] = snapshots[0].model_copy(update={"restored": True})

    failure_class = state.failure.failure_class if state.failure else "execution"
    move = _repair_move(failure_class, state, ctx)

    # Dead-end avoidance: if the chosen approach matches a retrieved dead end, switch.
    suppressed = _suppress_repeated_approach(state, ctx, move["approach"])
    if suppressed:
        move = suppressed

    template_note = ""
    signature = _failure_signature(state, failure_class)
    store = getattr(ctx, "patch_templates", None)
    if store is not None and signature:
        template = store.get(signature)
        if template is not None:
            move = {
                "name": f"apply_template:{template.template_id}",
                "approach": move["approach"],
                "reason": f"apply published template {template.template_id}",
                "strategy": state.strategy,
            }
            template_note = f"; template={template.template_id}"

    updates: dict = {
        "workspace_snapshots": snapshots,
        "failure_signal": None,
        # Clear prior attempt transcript so solve→validate path is fresh.
        "transcript_ref": None,
    }
    if move.get("strategy"):
        updates["strategy"] = move["strategy"]
        updates["strategy_reason"] = move["reason"]
    if move.get("drop_chosen"):
        updates["chosen"] = None
        updates["bundle"] = state.bundle.model_copy(
            update={"skills": [s for s in state.bundle.skills if s != state.chosen]}
        )

    new_state = state.model_copy(update=updates)
    return NodeOutcome(
        state=new_state,
        route="always",
        note=(
            f"{note_prefix}restored={clean_ref!r}; move={move['name']}; "
            f"approach={move['approach']}{template_note}"
        ),
    )


def _repair_move(failure_class: str, state: RunState, ctx: NodeContext) -> dict:
    approach = _current_approach(state)
    if failure_class == "environment":
        return {
            "name": "repair_environment",
            "approach": approach,
            "reason": "environment failure: keep strategy, repair workspace via restore",
            "strategy": state.strategy,
        }
    if failure_class == "tool":
        return {
            "name": "retry_backoff",
            "approach": approach,
            "reason": "tool failure: retry same approach after restore (backoff is temporal)",
            "strategy": state.strategy,
        }
    if failure_class == "retrieval":
        return {
            "name": "drop_and_rereetrieve",
            "approach": "scratch",
            "reason": "retrieval failure: drop candidate, fall back to scratch",
            "strategy": "scratch",
            "drop_chosen": True,
        }
    if failure_class == "plan":
        next_strategy = "scratch" if state.strategy != "scratch" else "adapt"
        return {
            "name": "switch_strategy",
            "approach": next_strategy,
            "reason": f"plan failure: switch strategy {state.strategy} → {next_strategy}",
            "strategy": next_strategy,
            "drop_chosen": state.strategy == "apply",
        }
    if failure_class == "execution":
        return {
            "name": "patch_artifacts",
            "approach": approach,
            "reason": "execution failure: restore and retry with same strategy (patch via criteria)",
            "strategy": state.strategy,
        }
    if failure_class == "merge":
        return {
            "name": "redispatch_serial",
            "approach": approach,
            "reason": "merge failure: re-dispatch from snapshot, serialised",
            "strategy": state.strategy,
        }
    return {
        "name": "noop_restore",
        "approach": approach,
        "reason": f"no evolve move for class {failure_class}; restore only",
        "strategy": state.strategy,
    }


def _failure_signature(state: RunState, failure_class: str) -> str:
    from recertia.memory.episodic.clusters import normalize_signature

    why = ""
    if state.failure_signal:
        why = state.failure_signal.detail
    elif state.failure and state.failure.evidence:
        why = state.failure.evidence[0]
    else:
        why = failure_class
    return normalize_signature(why, failure_class)


def _current_approach(state: RunState) -> str:
    if state.chosen is not None:
        return f"skill:{state.chosen.skill_id}@v{state.chosen.version}"
    return f"strategy:{state.strategy or 'scratch'}"


def _suppress_repeated_approach(state: RunState, ctx: NodeContext, approach: str) -> dict | None:
    if ctx.episodic is None:
        return None
    dead_ends = ctx.episodic.dead_ends_for(task_class=state.task.task_class, limit=5)
    for case in dead_ends:
        if case.dead_end and ctx.episodic.approach_still_applies(
            case.dead_end, current_approach=approach
        ):
            return {
                "name": "avoid_dead_end",
                "approach": "scratch",
                "reason": (
                    f"suppressing approach {approach!r}: dead end "
                    f"{case.dead_end.why_failed!r}"
                ),
                "strategy": "scratch",
                "drop_chosen": True,
            }
    return None
