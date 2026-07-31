"""Procedural retrieval pipeline (specs §5).

Stages, in order: candidate generation → RRF merge → filter (preconditions, active set,
lifecycle, env fingerprint) → rerank → score floor → evidence/staleness/curation demotion →
top-3 return. Thin evidence is demoted, never hard-dropped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from contracts.run import MemoryBundle, SkillCandidateRef
from fandea.retrieval.config import RetrievalConfig
from fandea.retrieval.index import SkillIndex, cosine, embed_text, tokenize
from fandea.retrieval.preconditions import (
    environment_fingerprint_matches,
    evaluate_all,
    parse_preconditions_json,
)


@dataclass
class DropRecord:
    skill_id: str
    version: int
    stage: str
    reason: str


@dataclass
class RetrievalExplanation:
    """What ``fandea skills search --explain`` prints."""

    query: str
    snapshot_id: str
    lexical_hits: list[tuple[str, int, float]] = field(default_factory=list)
    vector_hits: list[tuple[str, int, float]] = field(default_factory=list)
    merged: list[tuple[str, int, float]] = field(default_factory=list)
    probe_evidence: dict[tuple[str, int], list[dict[str, object]]] = field(default_factory=dict)
    dropped: list[DropRecord] = field(default_factory=list)
    demoted: list[tuple[str, int, float, str]] = field(default_factory=list)
    returned: list[SkillCandidateRef] = field(default_factory=list)


def reciprocal_rank_fusion(
    ranked_lists: list[list[tuple[str, int, float]]],
    k: int = 60,
) -> list[tuple[str, int, float]]:
    """RRF over ``(skill_id, version, _)`` lists; returns ``(skill_id, version, rrf_score)``."""

    scores: dict[tuple[str, int], float] = {}
    for ranked in ranked_lists:
        for rank, (sid, ver, _) in enumerate(ranked, start=1):
            scores[(sid, ver)] = scores.get((sid, ver), 0.0) + 1.0 / (k + rank)
    return sorted(
        [(sid, ver, score) for (sid, ver), score in scores.items()],
        key=lambda t: t[2],
        reverse=True,
    )


class Retriever:
    def __init__(self, index: SkillIndex, config: RetrievalConfig | None = None) -> None:
        self.index = index
        self.config = config or RetrievalConfig()

    def search(
        self,
        query: str,
        *,
        workdir: Path,
        env_fingerprint: dict[str, str] | None = None,
        readable_scopes: set[str] | None = None,
        suppress: bool = False,
    ) -> tuple[MemoryBundle, RetrievalExplanation]:
        cfg = self.config
        env_fingerprint = env_fingerprint or {}
        readable_scopes = readable_scopes or {"run", "project", "org", "global"}
        explanation = RetrievalExplanation(query=query, snapshot_id=self.index.snapshot_id())

        if suppress:
            return MemoryBundle(suppressed=True), explanation

        lexical = self.index.lexical_top_k(query, cfg.lexical_top_k)
        vector = self.index.vector_top_k(query, cfg.vector_top_k)
        explanation.lexical_hits = lexical
        explanation.vector_hits = vector

        merged = reciprocal_rank_fusion([lexical, vector], k=cfg.rrf_k)
        explanation.merged = merged

        survivors: list[tuple[str, int, float, dict]] = []
        for sid, ver, rrf_score in merged:
            row = self.index.get_row(sid, ver)
            if row is None:
                continue
            drop = self._filter_row(row, workdir, env_fingerprint, readable_scopes, explanation)
            if drop is not None:
                explanation.dropped.append(drop)
                continue
            survivors.append((sid, ver, rrf_score, row))

        # Rerank top N against the query by cosine over the stored document embedding,
        # blended with lexical overlap. Hashed bag-of-words embeddings are coarse; overlap
        # carries most of the signal for short chore-style queries.
        q_emb = embed_text(query)
        reranked: list[tuple[str, int, float, dict]] = []
        for sid, ver, rrf, row in survivors[: cfg.rerank_top_n]:
            doc_emb = embed_text(row["document"])
            vec = cosine(q_emb, doc_emb)
            overlap = _lexical_overlap(query, row["document"])
            # Prefer skills whose id tokens appear in the query (strong chore-label signal).
            id_boost = 0.15 if _id_tokens_in_query(sid, query) else 0.0
            score = 0.35 * vec + 0.50 * overlap + id_boost + 0.15 * min(rrf * 20.0, 1.0)
            reranked.append((sid, ver, score, row))
        for sid, ver, rrf, row in survivors[cfg.rerank_top_n :]:
            reranked.append((sid, ver, min(rrf * 20.0, cfg.min_score), row))
        reranked.sort(key=lambda t: t[2], reverse=True)

        floored: list[tuple[str, int, float, dict]] = []
        for sid, ver, score, row in reranked:
            if score < cfg.min_score:
                explanation.dropped.append(
                    DropRecord(sid, ver, "score_floor", f"score={score:.3f}<{cfg.min_score}")
                )
                continue
            floored.append((sid, ver, score, row))

        final: list[tuple[str, int, float, dict]] = []
        for sid, ver, score, row in floored:
            demoted_score, demote_reason = self._demote(score, row)
            if demote_reason:
                explanation.demoted.append((sid, ver, demoted_score, demote_reason))
            final.append((sid, ver, demoted_score, row))
        final.sort(key=lambda t: t[2], reverse=True)

        candidates: list[SkillCandidateRef] = []
        for rank, (sid, ver, score, row) in enumerate(final[: cfg.max_candidates], start=1):
            candidates.append(
                SkillCandidateRef(
                    skill_id=sid,
                    version=ver,
                    score=round(score, 4),
                    lexical_rank=_rank_of(lexical, sid, ver),
                    vector_rank=_rank_of(vector, sid, ver),
                )
            )
            # silence unused
            _ = rank
            _ = row

        explanation.returned = candidates
        return MemoryBundle(skills=candidates), explanation

    def _filter_row(
        self,
        row: dict,
        workdir: Path,
        env_fingerprint: dict[str, str],
        readable_scopes: set[str],
        explanation: RetrievalExplanation,
    ) -> DropRecord | None:
        sid, ver = row["skill_id"], int(row["version"])
        # Shadow evidence is collected by the dedicated shadow runner.  It
        # must never be offered as an online caller-visible candidate.
        if row["lifecycle"] != "approved":
            return DropRecord(sid, ver, "lifecycle", f"lifecycle={row['lifecycle']}")
        # Approved skills must be in the bounded active set to apply.
        if not row["active"]:
            return DropRecord(sid, ver, "active_set", "approved but active=False")
        if row["scope"] not in readable_scopes:
            return DropRecord(sid, ver, "scope", f"scope={row['scope']} not readable")

        skill_fp = json.loads(row["tool_fingerprint_json"])
        ok, reason = environment_fingerprint_matches(skill_fp, env_fingerprint)
        if not ok:
            return DropRecord(sid, ver, "env_fingerprint", reason)

        preconditions = parse_preconditions_json(row["preconditions_json"])
        ok, evidence = evaluate_all(preconditions, workdir, budget_units=self.config.probe_budget_units)
        explanation.probe_evidence[(sid, ver)] = [
            {
                "probe": item.probe,
                "passed": item.passed,
                "detail": item.detail,
                "cost_units": item.cost_units,
            }
            for item in evidence
        ]
        if not ok:
            return DropRecord(
                sid, ver, "precondition", evidence[-1].reason if evidence else "failed"
            )
        return None

    def _demote(self, score: float, row: dict) -> tuple[float, str | None]:
        cfg = self.config
        reasons: list[str] = []
        applications = int(row["applications"])
        if applications < cfg.evidence_floor:
            score *= cfg.low_evidence_factor
            reasons.append(f"thin_evidence:applications={applications}<{cfg.evidence_floor}")

        curation = row["curation"]
        if curation == "human_authored":
            score *= cfg.human_authored_prior
        elif curation == "mined_from_human_artifact":
            score *= cfg.mined_prior
            reasons.append("curation_prior:mined")
        else:
            score *= cfg.self_distilled_prior
            reasons.append("curation_prior:self_distilled")

        last_used = row["last_used_at"]
        if last_used:
            try:
                ts = datetime.fromisoformat(last_used)
                age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
                if age_days > 0:
                    decay = 0.5 ** (age_days / cfg.staleness_half_life_days)
                    score *= decay
                    if decay < 0.99:
                        reasons.append(f"staleness:age_days={age_days:.1f},factor={decay:.3f}")
            except ValueError:
                pass

        return score, "; ".join(reasons) if reasons else None


def _rank_of(hits: list[tuple[str, int, float]], skill_id: str, version: int) -> int | None:
    for i, (sid, ver, _) in enumerate(hits, start=1):
        if sid == skill_id and ver == version:
            return i
    return None


def _lexical_overlap(query: str, document: str) -> float:
    q = set(tokenize(query))
    d = set(tokenize(document))
    if not q:
        return 0.0
    return len(q & d) / len(q)


def _id_tokens_in_query(skill_id: str, query: str) -> bool:
    id_tokens = set(skill_id.split("-"))
    q_tokens = set(tokenize(query))
    # Require at least half the id tokens to appear (avoids boosting on a lone "add").
    if not id_tokens:
        return False
    return len(id_tokens & q_tokens) >= max(2, (len(id_tokens) + 1) // 2)
