"""Judge criterion evaluation under verifier isolation (specs §6, §26.3)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from contracts.common import Lens
from contracts.criteria import CriterionResult, TaskCriterion
from recertia.solver.model import ModelClient


def artifact_only_context(
    *,
    artifact_text: str,
    rubric: str,
    lens: Lens | None,
) -> dict[str, Any]:
    """Build the ONLY context a judge may see — never transcript/plan/justification."""

    return {
        "artifact": artifact_text,
        "rubric": rubric,
        "lens": lens,
    }


def context_hash(ctx: dict[str, Any]) -> str:
    blob = json.dumps(ctx, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def read_artifact(workdir: Path, artifact_path: str | None = None) -> str:
    """Load the artifact file the judge will score (default: ``output.txt``)."""

    path = workdir / (artifact_path or "output.txt")
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")[-8000:]
    names = sorted(p.name for p in workdir.iterdir()) if workdir.exists() else []
    return f"<no artifact file; workspace entries: {names}>"


def evaluate_judge(
    criterion: TaskCriterion,
    *,
    workdir: Path,
    model: ModelClient,
    artifact_path: str | None = None,
) -> CriterionResult:
    """Score a judge criterion in a fresh artifact+rubric context; record isolation evidence."""

    assert criterion.kind == "judge" and criterion.rubric is not None
    artifact = read_artifact(workdir, artifact_path)
    ctx = artifact_only_context(
        artifact_text=artifact, rubric=criterion.rubric, lens=criterion.lens
    )
    # Isolation invariant: these keys must never appear in the judge context.
    for forbidden in ("transcript", "plan", "justification", "solver"):
        if forbidden in ctx:
            raise RuntimeError(f"judge context isolation violated: key {forbidden!r} present")
    digest = context_hash(ctx)
    prompt = (
        "You are an isolated verifier. You receive ONLY an artifact and a rubric.\n"
        f"Lens: {criterion.lens or 'correctness'}\n"
        f"Rubric:\n{criterion.rubric}\n\n"
        f"Artifact:\n{artifact}\n\n"
        "Reply with exactly PASS or FAIL on the first line."
    )
    response = model.complete(prompt, system="isolated-judge")
    first = (
        response.text.strip().splitlines()[0].strip().upper() if response.text.strip() else "FAIL"
    )
    passed = first.startswith("PASS")
    return CriterionResult(
        criterion_id=criterion.id,
        kind="judge",
        passed=passed,
        weight=criterion.weight,
        isolation="fresh_context",
        lens=criterion.lens,
        context_hash=digest,
        output_excerpt=response.text[:2000],
        duration_s=response.latency_s,
    )


def assert_distinct_lenses(criteria: list[TaskCriterion]) -> None:
    """Multiple judges in one set must use distinct lenses (specs §26.3)."""

    lenses = [c.lens for c in criteria if c.kind == "judge"]
    if len(lenses) != len(set(lenses)):
        raise ValueError("multiple judge criteria must declare distinct lens values")
