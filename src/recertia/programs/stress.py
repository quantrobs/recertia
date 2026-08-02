"""Stress checks for migration programs / Goal packs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from contracts.goal import Goal
from contracts.program import MigrationProgram, MigrationStep
from recertia.programs.materialize import freeze_mutate_overlap


@dataclass
class StressWarning:
    code: str
    message: str
    severity: Literal["info", "warn", "block"] = "warn"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stress_step(
    program: MigrationProgram,
    step: MigrationStep,
    *,
    goal: Goal | None = None,
) -> list[StressWarning]:
    warnings: list[StressWarning] = []
    g = goal or step.goal
    hard = [d for d in g.desired if d.weight >= 1.0 and d.kind != "judge"]
    if not hard:
        warnings.append(
            StressWarning(
                code="no_hard_criteria",
                message="Step Goal has no required non-judge desired states",
                severity="block",
            )
        )

    overlap = freeze_mutate_overlap(step)
    if overlap:
        warnings.append(
            StressWarning(
                code="freeze_mutate_overlap",
                message=f"Paths in both freeze and mutate: {overlap}",
                severity="block",
            )
        )

    if step.freeze_paths and program.freeze_enforcement == "advisory":
        warnings.append(
            StressWarning(
                code="freeze_advisory",
                message=(
                    "freeze_paths are advisory in GP0; must_not_modify is not injected "
                    "until freeze_enforcement=hard"
                ),
                severity="info",
            )
        )

    for d in g.desired:
        if d.kind == "command" and (d.run or "").strip() in {"true", ":", "exit 0"}:
            warnings.append(
                StressWarning(
                    code="vacuous_command",
                    message=f"Desired {d.id!r} command is vacuous",
                    severity="block",
                )
            )

    cmds = [d for d in g.desired if d.kind == "command"]
    if cmds and all(
        (d.run or "").strip() in {"python -m pytest -q", "pytest -q", "pytest"}
        for d in cmds
    ):
        warnings.append(
            StressWarning(
                code="generic_pytest_only",
                message="Only whole-suite pytest; prefer seam-specific checks",
                severity="warn",
            )
        )

    if step.role == "structural":
        priors = [s for s in program.steps if s.ordinal < step.ordinal]
        char_ok = any(
            s.role == "characterization" and s.status in {"succeeded", "skipped"}
            for s in priors
        )
        if priors and not char_ok and not any(s.role == "characterization" for s in priors):
            warnings.append(
                StressWarning(
                    code="weak_characterization",
                    message="Structural step without a prior characterization step",
                    severity="warn",
                )
            )

    if (
        program.handoff in {"copy_forward", "git_tip"}
        and program.handoff != "none"
    ):
        warnings.append(
            StressWarning(
                code="missing_handoff",
                message=f"handoff={program.handoff} is not available in GP0 runtime",
                severity="warn",
            )
        )

    if (
        step.acceptance_gate.require_program_bar
        and step.role != "characterization"
        and not program.program_bar_desired
        and not program.program_bar_constraints
        and step.ordinal > 0
    ):
        warnings.append(
            StressWarning(
                code="program_bar_dropped",
                message="No program_bar defined for later steps",
                severity="warn",
            )
        )

    return warnings


def stress_program(program: MigrationProgram) -> list[StressWarning]:
    out: list[StressWarning] = []
    total_hard = 0
    for step in program.steps:
        out.extend(stress_step(program, step))
        total_hard += sum(
            1 for d in step.goal.desired if d.weight >= 1.0 and d.kind != "judge"
        )
    if len(program.steps) == 1 and total_hard > 8:
        out.append(
            StressWarning(
                code="mega_goal",
                message="Single step with many hard desired states — prefer a program",
                severity="warn",
            )
        )
    return out
