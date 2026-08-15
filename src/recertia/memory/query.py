"""Federated retrieve debug across procedural / semantic / episodic planes (RW-SUR)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from recertia.memory.affordance import AffordanceStore
from recertia.memory.episodic import EpisodicStore
from recertia.memory.procedural.store import SkillStore
from recertia.memory.semantic import FactStore
from recertia.retrieval.index import SkillIndex
from recertia.retrieval.pipeline import Retriever


def federated_query(
    query: str,
    *,
    skills_root: Path | str,
    facts_root: Path | str,
    episodic_root: Path | str,
    index_path: Path | str,
    workdir: Path | str,
    env_fingerprint: dict[str, str] | None = None,
    limit: int = 8,
    affordance_path: Path | str | None = None,
) -> dict[str, Any]:
    """Score + drop reasons across planes. Does not start a run."""

    store = SkillStore(skills_root)
    index = SkillIndex(index_path)
    try:
        fingerprint = store.library_fingerprint()
        if not index.is_fresh(fingerprint):
            index.rebuild(store.iter_loaded(), library_fingerprint=fingerprint)
        retriever = Retriever(index)
        bundle, explanation = retriever.search(
            query,
            workdir=Path(workdir),
            env_fingerprint=env_fingerprint or {},
        )
    finally:
        index.close()

    facts = FactStore(facts_root).retrieve(query, limit=limit)
    episodic = EpisodicStore(episodic_root)
    cases = episodic.list_index()[-limit:]
    affordances: dict[str, Any] = {"tools": [], "resources": []}
    if affordance_path is not None:
        aff = AffordanceStore(affordance_path)
        affordances = {
            "tools": [
                {
                    "tool": t.tool,
                    "invocations": t.invocations,
                    "failure_rate": t.failure_rate,
                }
                for t in aff.tools.values()
            ],
            "resources": [
                {"kind": r.kind, "id": r.id, "conflicts": r.conflicts}
                for r in aff.resources.values()
            ],
        }
    return {
        "query": query,
        "snapshot_id": explanation.snapshot_id,
        "skills": {
            "returned": [
                {"skill_id": c.skill_id, "version": c.version, "score": c.score}
                for c in bundle.skills
            ],
            "dropped": [
                {
                    "skill_id": d.skill_id,
                    "version": d.version,
                    "stage": d.stage,
                    "reason": d.reason,
                }
                for d in explanation.dropped
            ],
            "demoted": [
                {
                    "skill_id": sid,
                    "version": ver,
                    "score": score,
                    "reason": reason,
                }
                for sid, ver, score, reason in explanation.demoted
            ],
        },
        "facts": [f.model_dump(mode="json") for f in facts],
        "cases": cases,
        "affordances": affordances,
    }
