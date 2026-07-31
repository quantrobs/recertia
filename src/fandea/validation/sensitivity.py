"""Sensitivity-proof authoring: execute a criterion against a known-bad fixture (specs §15)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from contracts.criteria import SensitivityProof, SkillCertificationCriterion, TaskCriterion


def sensitivity_evidence_hash(
    criterion: TaskCriterion | SkillCertificationCriterion, negative_fingerprint: str
) -> str:
    """Hash exactly the executable criterion and immutable negative-fixture fingerprint."""

    criterion_payload = criterion.model_dump(
        mode="json", exclude={"sensitivity_proof"}, exclude_none=False
    )
    encoded = json.dumps(criterion_payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded + b"\0" + negative_fingerprint.encode()).hexdigest()


def workspace_fingerprint(workdir: Path) -> str:
    """Stable hash of file paths + contents under ``workdir`` (for ``checked_against``)."""

    h = hashlib.sha256()
    if not workdir.exists():
        return h.hexdigest()
    for path in sorted(workdir.rglob("*")):
        if path.is_file():
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
    if criterion.kind == "command":
        assert criterion.run is not None
        proc = subprocess.run(
            criterion.run,
            shell=True,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=criterion.timeout_s,
        )
        return proc.returncode == criterion.expect_exit
    if criterion.kind == "assertion":
        assert criterion.expr is not None
        ns = {"workdir": workdir, "Path": Path}
        return bool(eval(criterion.expr, {"__builtins__": {}}, ns))  # noqa: S307
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
