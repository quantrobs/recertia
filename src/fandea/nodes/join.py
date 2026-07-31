"""``join``: audit completeness and select/reduce fan-out branches (M6)."""

from __future__ import annotations

import shutil
from itertools import islice
from pathlib import Path

from contracts.branch import MergeAudit
from contracts.failure import FailureSignal, FailureVerdict
from contracts.run import Artifact, RunState
from fandea.nodes._util import now
from fandea.nodes.context import NodeContext, NodeOutcome
from fandea.nodes.validate import score_criteria

LAYER_THRESHOLD = 8
"""Merges at or above this input count use layered fan-in (specs §26.4)."""


def join(state: RunState, ctx: NodeContext) -> NodeOutcome:
    expected = len(state.branches)
    received = sum(1 for b in state.branches if b.status in ("succeeded", "failed"))
    missing = [b.branch_id for b in state.branches if b.status not in ("succeeded", "failed")]
    layered = expected >= LAYER_THRESHOLD

    if missing:
        # One-shot re-dispatch of missing only (record audit, signal merge).
        audit = MergeAudit(
            merge_id=f"{ctx.run_id}-join-{len(state.merge_audits)}",
            expected=expected,
            received=received,
            missing=missing,
            action="flagged",
            layered=layered,
        )
        new_state = state.model_copy(
            update={
                "merge_audits": [*state.merge_audits, audit],
                "failure_signal": FailureSignal(
                    source="join", detail=f"merge gap: missing={missing}", at=now()
                ),
                "failure": FailureVerdict(
                    failure_class="merge",
                    evidence=[f"missing branches: {missing}"],
                    counts_against_trust=False,
                    escalate_to_human=False,
                ),
            }
        )
        return NodeOutcome(
            state=new_state,
            route="otherwise",
            note=f"merge gap visible: missing={missing}",
        )

    batches: list[list[str]] = []
    audit = MergeAudit(
        merge_id=f"{ctx.run_id}-join-{len(state.merge_audits)}",
        expected=expected,
        received=received,
        missing=[],
        action="proceeded",
        layered=layered,
    )

    survivor_ids: set[str] | None = None
    if layered and state.strategy == "portfolio":
        # Mechanical reduction: keep top half by score, then select winner among survivors.
        ranked = sorted(
            [b for b in state.branches if b.status == "succeeded"],
            key=_portfolio_score,
            reverse=True,
        )
        keep = {b.branch_id for b in ranked[: max(2, len(ranked) // 2)]} or {
            b.branch_id for b in ranked[:1]
        }
        survivor_ids = keep
        state = state.model_copy(
            update={
                "branches": [
                    b if b.branch_id in keep else b.model_copy(update={"selected": False})
                    for b in state.branches
                ]
            }
        )

    if state.strategy == "portfolio" or any(b.kind == "portfolio" for b in state.branches):
        winner = _select_portfolio_winner(state, eligible_ids=survivor_ids)
        branches = []
        for b in state.branches:
            branches.append(
                b.model_copy(update={"selected": b.branch_id == winner.branch_id})
                if winner
                else b
            )
        exclude = {b.branch_id for b in state.branches} | {".fan-in"}
        if winner is not None and winner.workspace_ref:
            _materialize_portfolio_winner(Path(winner.workspace_ref), ctx, exclude=exclude)
        results, failure_signal, notes = score_criteria(state, ctx)
        updates: dict = {
            "branches": branches,
            "results": results,
            "results_history": [*state.results_history, results],
            "failure_signal": failure_signal,
            "merge_audits": [*state.merge_audits, audit],
        }
        if winner is not None and winner.workspace_ref:
            updates["artifacts"] = [
                *state.artifacts,
                Artifact(
                    kind="file",
                    ref=winner.workspace_ref,
                    description="materialized portfolio winner",
                ),
            ]
        new_state = state.model_copy(update=updates)
        note = (
            f"portfolio winner={winner.branch_id if winner else None}"
            + (" layered" if layered else "")
        )
        if notes:
            note += "; " + "; ".join(notes)
    else:
        # Decomposition: all must succeed.
        if any(b.status != "succeeded" for b in state.branches):
            new_state = state.model_copy(
                update={
                    "merge_audits": [
                        *state.merge_audits,
                        audit.model_copy(update={"action": "failed"}),
                    ],
                    "failure_signal": FailureSignal(
                        source="solver", detail="decomposition branch failed", at=now()
                    ),
                }
            )
            return NodeOutcome(state=new_state, route="otherwise", note="decomposition incomplete")
        exclude = {b.branch_id for b in state.branches} | {".fan-in"}
        try:
            merged_ref, batches = _materialize_decomposition(
                state, ctx, layered=layered, exclude=exclude
            )
        except ValueError as exc:
            failed_audit = audit.model_copy(update={"action": "failed", "batches": batches})
            new_state = state.model_copy(
                update={
                    "merge_audits": [*state.merge_audits, failed_audit],
                    "failure_signal": FailureSignal(source="join", detail=str(exc), at=now()),
                }
            )
            return NodeOutcome(state=new_state, route="otherwise", note="decomposition merge conflict")

        # Branch-owned scores prove local progress; routing is based on a fresh score of
        # the materialized parent artifact, including join-only criteria.
        results, failure_signal, notes = score_criteria(state, ctx)
        audit = audit.model_copy(update={"batches": batches})
        new_state = state.model_copy(
            update={
                "results": results,
                "results_history": [*state.results_history, results],
                "failure_signal": failure_signal,
                "artifacts": [
                    *state.artifacts,
                    Artifact(kind="file", ref=merged_ref, description="materialized decomposition output"),
                ],
                "merge_audits": [*state.merge_audits, audit],
            }
        )
        note = "decomposition merge complete"
        if layered:
            note += " layered"
        if notes:
            note += "; " + "; ".join(notes)

    route = "merge_complete_and_passing"
    if new_state.failure_signal is not None:
        route = "otherwise"
    return NodeOutcome(state=new_state, route=route, note=note)


def _portfolio_score(b) -> tuple[int, float, float]:
    req_pass = sum(1 for r in b.results if r.weight >= 1.0 and r.passed)
    advisory = sum(r.weight for r in b.results if r.passed and r.weight < 1.0)
    cost = -(b.cost_usd or b.spent.cost_usd or 0.0)
    return (req_pass, advisory, cost)


def _select_portfolio_winner(state: RunState, *, eligible_ids: set[str] | None = None):
    """Select a portfolio winner, restricted to layered survivors when provided."""

    def _eligible(branches: list) -> list:
        if eligible_ids is None:
            return list(branches)
        return [b for b in branches if b.branch_id in eligible_ids]

    succeeded = _eligible([b for b in state.branches if b.status == "succeeded"])
    if succeeded:
        return max(succeeded, key=_portfolio_score)
    # Preserve a deterministic selected branch for audit/recovery even when the runtime
    # fails every branch before validation (for example, unavailable sandbox capacity).
    # The run still routes through failure because the parent criterion result/signals fail.
    completed = _eligible([b for b in state.branches if b.status in ("failed", "timed_out")])
    return max(completed, key=_portfolio_score) if completed else None


def _materialize_portfolio_winner(
    winner_workdir: Path, ctx: NodeContext, *, exclude: set[str]
) -> None:
    """Copy the selected portfolio workspace into the parent workdir."""

    if not winner_workdir.exists():
        return
    for path in winner_workdir.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(winner_workdir)
        if relative.parts and relative.parts[0] in exclude:
            continue
        destination = ctx.workdir / relative
        if destination.resolve() == path.resolve():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())


def _materialize_decomposition(
    state: RunState, ctx: NodeContext, *, layered: bool, exclude: set[str]
) -> tuple[str, list[list[str]]]:
    """Reduce branch workspaces into a parent artifact, using real bounded fan-in batches."""

    branches = [b for b in state.branches if b.kind == "decomposition"]
    sources: list[tuple[str, Path]] = [(b.branch_id, Path(b.workspace_ref)) for b in branches]
    root = ctx.workdir / ".fan-in"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir()
    batches: list[list[str]] = []
    width = 4 if layered else max(1, len(sources))
    level = 0
    while len(sources) > 1:
        next_sources: list[tuple[str, Path]] = []
        iterator = iter(sources)
        for batch_no, first in enumerate(iterator):
            group = [first, *list(islice(iterator, width - 1))]
            ids = [branch_id for branch_id, _ in group]
            batches.append(ids)
            target = root / f"level-{level}-batch-{batch_no}"
            _copy_baseline(ctx.workdir, target, exclude=exclude)
            _merge_changed_sources(ctx.workdir, [path for _, path in group], target)
            next_sources.append(("+".join(ids), target))
        sources = next_sources
        level += 1

    final = root / "final"
    _copy_baseline(ctx.workdir, final, exclude=exclude)
    if sources:
        _merge_changed_sources(ctx.workdir, [sources[0][1]], final)
    _copy_changed_files(ctx.workdir, final, ctx.workdir, exclude=exclude)
    return str(final), batches


def _copy_baseline(parent: Path, target: Path, *, exclude: set[str]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in parent.iterdir():
        if item.name in exclude or item.name.startswith("."):
            continue
        dest = target / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        elif item.is_file():
            shutil.copy2(item, dest)


def _merge_changed_sources(baseline: Path, sources: list[Path], target: Path) -> None:
    seen: dict[Path, bytes] = {}
    for source in sources:
        for path in source.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(source)
            original = baseline / relative
            data = path.read_bytes()
            if original.exists() and original.is_file() and original.read_bytes() == data:
                continue
            previous = seen.get(relative)
            if previous is not None and previous != data:
                raise ValueError(f"decomposition merge conflict at {relative}")
            seen[relative] = data
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)


def _copy_changed_files(
    baseline: Path, source: Path, target: Path, *, exclude: set[str]
) -> None:
    for path in source.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(source)
        # Do not copy branch or fan-in implementation directories into the artifact.
        if relative.parts and relative.parts[0] in exclude:
            continue
        destination = target / relative
        if destination == path:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
