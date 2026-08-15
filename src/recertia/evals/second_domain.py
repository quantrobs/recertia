"""Second-domain lift reporting: honest 'not established' when interval spans zero."""

from __future__ import annotations

from pathlib import Path

from contracts.eval import BinomialSample, CausalLiftResult
from recertia.evals.statistics import causal_lift


def research_synthesis_lift(
    *,
    treatment_successes: int,
    treatment_trials: int,
    control_successes: int,
    control_trials: int,
) -> CausalLiftResult:
    """Compute causal_lift for ``research-synthesis`` without claiming when CI includes 0."""

    return causal_lift(
        BinomialSample(successes=treatment_successes, trials=treatment_trials),
        BinomialSample(successes=control_successes, trials=control_trials),
        task_class="research-synthesis",
    )


def second_domain_fixture_ready(repo_root: Path | None = None) -> bool:
    root = (repo_root or Path.cwd()) / "evals/golden/research-synthesis/draft-structured-brief"
    return (root / "task.json").exists() and (root / "workspace" / "notes.md").exists()
