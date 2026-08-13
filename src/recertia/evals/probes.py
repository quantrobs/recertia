"""Labelled retrieval-precision probe runner (remaining-work RW-M2 / RW-4).

Uses the same ``Retriever.search`` path as a run. Precision matches the M1 engineering
gate: ``|relevant ∩ top3| / min(3, |relevant|)`` per probe (0 when ``relevant`` is empty),
then the mean.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from recertia.memory.procedural.store import SkillStore
from recertia.retrieval.index import SkillIndex
from recertia.retrieval.pipeline import Retriever

DEFAULT_PROBES = Path("evals/probes/repo-chore.json")
DEFAULT_ENV_FINGERPRINT = {"python": "3.12", "pytest": "8.3.4"}


@dataclass
class ProbeItemResult:
    probe_id: str
    precision: float
    top3: list[str]
    relevant: list[str]


@dataclass
class ProbeRunResult:
    task_class: str
    snapshot_id: str
    precision_at_3: float
    skill_count: int
    probes: list[ProbeItemResult] = field(default_factory=list)
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_payload(self) -> dict[str, Any]:
        return {
            "task_class": self.task_class,
            "snapshot_id": self.snapshot_id,
            "precision_at_3": self.precision_at_3,
            "skill_count": self.skill_count,
            "recorded_at": self.recorded_at.isoformat(),
            "probes": [
                {
                    "probe_id": p.probe_id,
                    "precision": p.precision,
                    "top3": p.top3,
                    "relevant": p.relevant,
                }
                for p in self.probes
            ],
        }


def load_probe_file(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("probes"), list):
        raise ValueError("probe file must be a JSON object with a probes array")
    return payload


def probe_precision(top3: set[str], relevant: set[str]) -> float:
    """Per-probe precision used by M1 and the remaining-work runner."""

    if not relevant:
        return 0.0
    denom = min(3, len(relevant))
    return len(top3 & relevant) / denom


def _materialise_workdir(root: Path, files: dict[str, str] | None) -> Path:
    workdir = root
    workdir.mkdir(parents=True, exist_ok=True)
    for rel, content in (files or {}).items():
        path = workdir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return workdir


def run_probes(
    *,
    probes_path: Path | str = DEFAULT_PROBES,
    skills_root: Path | str = Path("skills"),
    index_path: Path | str | None = None,
    workdir_root: Path | str | None = None,
    env_fingerprint: dict[str, str] | None = None,
    task_class: str | None = None,
) -> ProbeRunResult:
    """Run labelled probes through ``Retriever.search`` and return mean precision@3."""

    probes_file = Path(probes_path)
    payload = load_probe_file(probes_file)
    probes: list[dict[str, Any]] = list(payload["probes"])
    class_name = task_class or probes_file.stem
    store = SkillStore(skills_root)
    loaded = store.iter_loaded()
    skill_count = len({v.skill_id for v, _s, _st in loaded})
    index = SkillIndex(
        index_path or (Path(skills_root).parent / ".recertia" / "probe_index.db")
    )
    default_work = Path(skills_root).parent / ".recertia" / "probe-work"
    work_root = Path(workdir_root) if workdir_root is not None else default_work
    env = env_fingerprint or DEFAULT_ENV_FINGERPRINT
    try:
        fingerprint = store.library_fingerprint()
        if not index.is_fresh(fingerprint):
            index.rebuild(loaded, library_fingerprint=fingerprint)
        retriever = Retriever(index)
        snapshot_id = retriever.snapshot_id()
        items: list[ProbeItemResult] = []
        for probe in probes:
            probe_id = str(probe.get("id") or f"p{len(items)}")
            workdir = _materialise_workdir(
                work_root / probe_id, probe.get("workdir_files") or {}
            )
            bundle, _ = retriever.search(
                str(probe.get("request") or ""),
                workdir=workdir,
                env_fingerprint=env,
            )
            top3 = [c.skill_id for c in bundle.skills[:3]]
            relevant = [str(s) for s in (probe.get("relevant") or [])]
            items.append(
                ProbeItemResult(
                    probe_id=probe_id,
                    precision=probe_precision(set(top3), set(relevant)),
                    top3=top3,
                    relevant=relevant,
                )
            )
        mean = sum(p.precision for p in items) / len(items) if items else 0.0
        if not items:
            mean = 0.0
        return ProbeRunResult(
            task_class=class_name,
            snapshot_id=snapshot_id,
            precision_at_3=mean,
            skill_count=skill_count,
            probes=items,
        )
    finally:
        index.close()
