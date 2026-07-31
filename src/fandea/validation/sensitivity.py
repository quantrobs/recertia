"""Sensitivity-proof authoring: execute a criterion against a known-bad fixture (specs §15)."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from contracts.criteria import (
    SensitivityProof,
    SkillCertificationCriterion,
    TaskCriterion,
    sensitivity_evidence_hash,
    sensitivity_proof_binds,
)
from fandea.validation.assertions import UnsafeAssertionError, evaluate_assertion

__all__ = [
    "author_sensitivity_proof",
    "empty_negative_fixture",
    "mutate_workspace",
    "sensitivity_evidence_hash",
    "sensitivity_proof_binds",
    "workspace_fingerprint",
]


def workspace_fingerprint(workdir: Path) -> str:
    """Stable hash of file paths + contents under ``workdir`` (for ``checked_against``)."""

    h = hashlib.sha256()
    if not workdir.exists():
        return h.hexdigest()
    for path in sorted(workdir.rglob("*")):
        if path.is_file() and not path.is_symlink():
            try:
                resolved = path.resolve()
                resolved.relative_to(workdir.resolve())
            except ValueError:
                continue
            rel = path.relative_to(workdir).as_posix()
            h.update(rel.encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def author_sensitivity_proof(
    criterion: TaskCriterion | SkillCertificationCriterion,
    *,
    negative_workdir: Path,
    runner: Callable[[TaskCriterion | SkillCertificationCriterion, Path], bool] | None = None,
) -> SensitivityProof:
    """Run ``criterion`` against ``negative_workdir``; a vacuous criterion will not reject."""

    runner = runner or _default_runner
    rejected = not runner(criterion, negative_workdir)
    negative_fingerprint = workspace_fingerprint(negative_workdir)
    return SensitivityProof(
        criterion_id=criterion.id,
        negative_fixture=str(negative_workdir),
        rejected=rejected,
        checked_at=datetime.now(timezone.utc),
        checked_against=f"sha256:{negative_fingerprint}",
        evidence_hash=sensitivity_evidence_hash(criterion, negative_fingerprint),
    )


def empty_negative_fixture(parent: Path | None = None) -> Path:
    """Create an empty temporary workspace used as the default negative fixture."""

    return Path(tempfile.mkdtemp(prefix="fandea-neg-", dir=parent))


def mutate_workspace(source: Path, *, drop_files: bool = True) -> Path:
    """Clone ``source`` then clear files so a real criterion should fail."""

    dest = Path(tempfile.mkdtemp(prefix="fandea-mut-"))
    if source.exists():
        for item in source.iterdir():
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
    if drop_files:
        for path in list(dest.rglob("*")):
            if path.is_file():
                path.unlink()
    return dest


def _default_runner(
    criterion: TaskCriterion | SkillCertificationCriterion, workdir: Path
) -> bool:
    """Run criteria through the configured sandbox / restricted assertion language."""

    if criterion.kind == "command":
        assert criterion.run is not None
        from fandea.solver.container import run_configured_command
        from fandea.solver.sandbox import SandboxError

        try:
            proc = run_configured_command(
                criterion.run, workdir=workdir, timeout_s=criterion.timeout_s
            )
        except SandboxError:
            return False
        return proc.returncode == criterion.expect_exit
    if criterion.kind == "assertion":
        assert criterion.expr is not None
        try:
            return evaluate_assertion(criterion.expr, workdir=workdir)
        except UnsafeAssertionError:
            return False
    if criterion.kind in ("schema", "metric"):
        from fandea.graph.ops import OperationLedger
        from fandea.ledger import HashChainLedger
        from fandea.nodes.context import NodeContext
        from fandea.nodes.validate import _score_criterion
        from fandea.workspace import WorkspaceManager

        # Mechanical proof against the negative fixture workdir — same runners as validate.
        ctx = NodeContext(
            run_id="sensitivity",
            attempt_no=0,
            node="sensitivity",
            workdir=workdir,
            workspaces=WorkspaceManager(workdir / ".snapshots"),
            ledger=HashChainLedger(workdir / ".ledger.jsonl"),
            ops=OperationLedger(workdir / ".ops.db"),
        )
        return _score_criterion(criterion, ctx).passed
    # Judges cannot author a mechanical proof here — treat as not rejected.
    return True
