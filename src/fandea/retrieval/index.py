"""Procedural-plane index: FTS5 lexical + hashed bag-of-words embeddings (M1).

Embeddings are deterministic and dependency-free: a fixed-dim hashed unigram/bigram vector
over ``title + intent + tags + tool names``. Good enough for ranking and for a reproducible
``index_snapshot_id``; a real embedding model can replace ``embed_text`` later without
changing the index schema.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
from pathlib import Path

from contracts.skill import SkillVersion
from contracts.stats import SkillStats
from contracts.status import SkillStatus

EMBED_DIM = 64
_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def embed_text(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Hashed bag-of-words embedding; L2-normalised. Deterministic across processes."""

    vec = [0.0] * dim
    tokens = tokenize(text)
    grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    for gram in grams:
        h = int(hashlib.sha256(gram.encode()).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) & 1 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def skill_document(version: SkillVersion) -> str:
    tools = " ".join(step.tool or "" for step in version.steps)
    tags = " ".join(version.tags)
    return f"{version.title}\n{version.intent}\n{tags}\n{tools}\n{version.task_class}"


class SkillIndex:
    """SQLite FTS5 + embedding store for one library snapshot."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS skills (
                    skill_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    task_class TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'project',
                    lifecycle TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    curation TEXT NOT NULL,
                    applications INTEGER NOT NULL DEFAULT 0,
                    last_used_at TEXT,
                    tool_fingerprint_json TEXT NOT NULL DEFAULT '{}',
                    preconditions_json TEXT NOT NULL DEFAULT '[]',
                    document TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    PRIMARY KEY (skill_id, version)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
                    skill_id, version UNINDEXED, document, tokenize='porter'
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def rebuild(
        self,
        entries: list[tuple[SkillVersion, SkillStatus, SkillStats]],
    ) -> str:
        """Replace the index contents; return the new ``index_snapshot_id``."""

        with self._lock:
            self._conn.execute("DELETE FROM skills")
            self._conn.execute("DELETE FROM skills_fts")
            for version, status, stats in entries:
                doc = skill_document(version)
                emb = embed_text(doc)
                fp = json.dumps(status.certification.tool_fingerprint)
                preconditions = json.dumps([p.model_dump() for p in version.preconditions])
                self._conn.execute(
                    """
                    INSERT INTO skills (
                        skill_id, version, task_class, scope, lifecycle, active, curation,
                        applications, last_used_at, tool_fingerprint_json, preconditions_json,
                        document, embedding_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version.skill_id,
                        version.version,
                        version.task_class,
                        version.scope,
                        status.lifecycle,
                        1 if status.active else 0,
                        version.provenance.curation,
                        stats.predictive_trust.applications,
                        (
                            stats.predictive_trust.last_used_at.isoformat()
                            if stats.predictive_trust.last_used_at
                            else None
                        ),
                        fp,
                        preconditions,
                        doc,
                        json.dumps(emb),
                    ),
                )
                self._conn.execute(
                    "INSERT INTO skills_fts (skill_id, version, document) VALUES (?, ?, ?)",
                    (version.skill_id, version.version, doc),
                )
            snapshot_id = self._compute_snapshot_id_unlocked()
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('snapshot_id', ?)",
                (snapshot_id,),
            )
            self._conn.commit()
        return snapshot_id

    def snapshot_id(self) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key='snapshot_id'"
            ).fetchone()
        return row[0] if row else self._compute_snapshot_id_unlocked()

    def _compute_snapshot_id_unlocked(self) -> str:
        rows = self._conn.execute(
            "SELECT skill_id, version, document FROM skills ORDER BY skill_id, version"
        ).fetchall()
        blob = json.dumps(rows, separators=(",", ":")).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def lexical_top_k(self, query: str, k: int) -> list[tuple[str, int, float]]:
        """Return ``(skill_id, version, rank_score)`` by FTS5 BM25 (lower BM25 is better)."""

        tokens = tokenize(query)
        if not tokens:
            return []
        # Quote each token for FTS5; OR-combine so partial matches still retrieve.
        match = " OR ".join(f'"{t}"' for t in tokens[:32])
        with self._lock:
            try:
                rows = self._conn.execute(
                    """
                    SELECT skills_fts.skill_id, skills_fts.version,
                           bm25(skills_fts) AS score
                    FROM skills_fts
                    WHERE skills_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (match, k),
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        # Convert BM25 (lower=better) to a descending rank score in (0, 1].
        out: list[tuple[str, int, float]] = []
        for i, (sid, ver, _bm25) in enumerate(rows):
            out.append((sid, int(ver), 1.0 / (1.0 + i)))
        return out

    def vector_top_k(self, query: str, k: int) -> list[tuple[str, int, float]]:
        q = embed_text(query)
        with self._lock:
            rows = self._conn.execute(
                "SELECT skill_id, version, embedding_json FROM skills"
            ).fetchall()
        scored = [
            (sid, int(ver), cosine(q, json.loads(emb)))
            for sid, ver, emb in rows
        ]
        scored.sort(key=lambda t: t[2], reverse=True)
        return scored[:k]

    def get_row(self, skill_id: str, version: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT skill_id, version, task_class, scope, lifecycle, active, curation,
                       applications, last_used_at, tool_fingerprint_json, preconditions_json,
                       document
                FROM skills WHERE skill_id=? AND version=?
                """,
                (skill_id, version),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "skill_id", "version", "task_class", "scope", "lifecycle", "active", "curation",
            "applications", "last_used_at", "tool_fingerprint_json", "preconditions_json",
            "document",
        )
        return dict(zip(keys, row))

    def all_rows(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT skill_id, version, task_class, scope, lifecycle, active, curation,
                       applications, last_used_at, tool_fingerprint_json, preconditions_json,
                       document
                FROM skills
                """
            ).fetchall()
        keys = (
            "skill_id", "version", "task_class", "scope", "lifecycle", "active", "curation",
            "applications", "last_used_at", "tool_fingerprint_json", "preconditions_json",
            "document",
        )
        return [dict(zip(keys, r)) for r in rows]
