"""Materialize migration steps into Goals (freeze + program bar merge)."""

from __future__ import annotations

from typing import Any

from contracts.budget import Budget
from contracts.goal import Constraint, DesiredState, Goal, compile_goal
from contracts.program import MigrationProgram, MigrationStep, budget_from_goal_constraints

HARD_FREEZE_RUNTIME_READY = True  # seal_must_not_modify_criteria enabled at intake


class MaterializeError(ValueError):
    """Invalid merge or GP0 execution prerequisites."""


def assert_freeze_enforcement_allowed(enforcement: str) -> None:
    """Reject dishonest hard freezes until snapshot sealing is enabled."""

    if enforcement == "hard" and not HARD_FREEZE_RUNTIME_READY:
        raise MaterializeError(
            "freeze_enforcement=hard is not available until must_not_modify "
            "snapshot sealing is enabled (GP1)"
        )

def _merge_desired(
    base: list[DesiredState], extra: list[DesiredState]
) -> list[DesiredState]:
    by_id = {d.id: d for d in base}
    for d in extra:
        if d.id in by_id and by_id[d.id].model_dump() != d.model_dump():
            raise MaterializeError(f"desired id collision with different body: {d.id!r}")
        by_id[d.id] = d
    return list(by_id.values())


def _merge_constraints(
    base: list[Constraint], extra: list[Constraint]
) -> list[Constraint]:
    by_id = {c.id: c for c in base}
    for c in extra:
        if c.id in by_id and by_id[c.id].model_dump() != c.model_dump():
            raise MaterializeError(f"constraint id collision with different body: {c.id!r}")
        by_id[c.id] = c
    return list(by_id.values())


def freeze_mutate_overlap(step: MigrationStep) -> list[str]:
    freeze = {p.rstrip("/") for p in step.freeze_paths}
    mutate = {p.rstrip("/") for p in step.mutate_paths}
    return sorted(freeze & mutate)


def materialize_step_goal(
    program: MigrationProgram,
    step: MigrationStep,
    *,
    apply_program_bar: bool = True,
) -> Goal:
    """Build the Goal that will be submitted for this step.

    GP0: ``freeze_enforcement=advisory`` does **not** inject ``must_not_modify``.
    Hard enforcement (later) injects freeze_paths as must_not_modify.
    """

    overlap = freeze_mutate_overlap(step)
    if overlap:
        raise MaterializeError(f"freeze_mutate_overlap: {overlap}")

    desired = list(step.goal.desired)
    constraints = list(step.goal.constraints)

    if apply_program_bar and step.acceptance_gate.require_program_bar:
        # Characterization steps typically establish the bar; still allow explicit bar items.
        if step.role != "characterization" or program.program_bar_desired:
            desired = _merge_desired(desired, list(program.program_bar_desired))
            constraints = _merge_constraints(
                constraints, list(program.program_bar_constraints)
            )

    if program.freeze_enforcement == "hard" and step.freeze_paths:
        freeze_id = f"freeze-{step.step_id}"
        constraints = _merge_constraints(
            constraints,
            [
                Constraint(
                    id=freeze_id,
                    kind="must_not_modify",
                    value=list(step.freeze_paths),
                )
            ],
        )

    return Goal(
        goal_id=step.goal.goal_id or f"{program.program_id}-{step.step_id}",
        desired=desired,
        constraints=constraints,
        context=step.goal.context,
        task_class=step.goal.task_class or program.task_class,
        preferences=dict(step.goal.preferences),
        strategy_hint=step.goal.strategy_hint,
    )


def preview_hash(goal: Goal) -> str:
    from recertia.nodes._util import criteria_hash

    return criteria_hash(compile_goal(goal))


def resolve_run_budget(goal: Goal, override: dict[str, Any] | None = None) -> Budget:
    base = Budget(**(override or {})) if override else Budget()
    return budget_from_goal_constraints(goal, base)


def previous_step(program: MigrationProgram, step: MigrationStep) -> MigrationStep | None:
    prior = [s for s in program.steps if s.ordinal == step.ordinal - 1]
    return prior[0] if prior else None


def step_is_ready(program: MigrationProgram, step: MigrationStep) -> bool:
    """Whether a step may start a new run (linear predecessor gate)."""

    if program.status != "active":
        return False
    if step.status not in {"planned", "ready", "failed"}:
        return False
    prev = previous_step(program, step)
    if prev is None:
        return True
    return prev.status in {"succeeded", "skipped"}


def assert_gp0_execution_prereqs(
    program: MigrationProgram,
    step: MigrationStep,
    *,
    workdir: str | None,
    plan_only: bool,
    workspace_id: str | None = None,
) -> None:
    """GP0 honesty: empty isolated workspaces are not a migration handoff."""

    if plan_only:
        return
    has_workdir = bool(workdir) or bool(workspace_id)
    if program.handoff == "none":
        # External git handoff or explicit operator workdir required to execute.
        eh = step.external_handoff
        has_ext = eh is not None and any(
            [eh.branch, eh.pr_url, eh.base_sha, eh.head_sha]
        )
        if not has_workdir and not has_ext:
            raise MaterializeError(
                "GP0 execution requires operator workdir and/or external_handoff "
                "(branch/pr_url/sha); use plan_only=true for board/preview without a run"
            )
    if program.handoff == "operator_workdir" and not has_workdir:
        raise MaterializeError("handoff=operator_workdir requires workdir or workspace_id")
    if program.handoff == "git_tip":
        if program.repo_binding is None:
            raise MaterializeError("handoff=git_tip requires a registered repo_binding")
    if program.handoff == "copy_forward":
        raise MaterializeError(
            "handoff=copy_forward is not supported; use git_tip or operator_workdir"
        )
