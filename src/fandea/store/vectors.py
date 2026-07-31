"""Vector index backends: JSON-blob (default), sqlite-vec when loaded, pgvector dialect."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Protocol

from fandea.retrieval.index import EMBED_DIM, cosine, embed_text


class VectorIndex(Protocol):
    def upsert(self, object_id: str, text: str, *, plane: str = "procedural") -> None: ...

    def search(
        self, query: str, *, plane: str = "procedural", limit: int = 10
    ) -> list[tuple[str, float]]: ...

    def backend_name(self) -> str: ...


class JsonBlobVectorIndex:
    """Dependency-free hashed embeddings stored as JSON (current v1 default)."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS vectors ("
            "plane TEXT NOT NULL, object_id TEXT NOT NULL, dims INTEGER NOT NULL, "
            "vector_json TEXT NOT NULL, PRIMARY KEY (plane, object_id))"
        )
        self._conn.commit()
        self._name = "json-blob"

    def backend_name(self) -> str:
        return self._name

    def upsert(self, object_id: str, text: str, *, plane: str = "procedural") -> None:
        vec = embed_text(text, EMBED_DIM)
        self._conn.execute(
            "INSERT OR REPLACE INTO vectors(plane, object_id, dims, vector_json) VALUES (?,?,?,?)",
            (plane, object_id, len(vec), json.dumps(vec)),
        )
        self._conn.commit()

    def search(self, query: str, *, plane: str = "procedural", limit: int = 10) -> list[tuple[str, float]]:
        q = embed_text(query, EMBED_DIM)
        rows = self._conn.execute(
            "SELECT object_id, vector_json FROM vectors WHERE plane = ?", (plane,)
        ).fetchall()
        scored = [(oid, cosine(q, json.loads(blob))) for oid, blob in rows]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def close(self) -> None:
        self._conn.close()


class SqliteVecIndex(JsonBlobVectorIndex):
    """Attempts to load the ``sqlite-vec`` extension; falls back to JSON blobs."""

    def __init__(self, db_path: Path | str) -> None:
        super().__init__(db_path)
        self._name = "json-blob"
        try:
            self._conn.enable_load_extension(True)
            # Common install names; ignore failures and keep JSON fallback.
            for ext in ("vec0", "sqlite_vec"):
                try:
                    self._conn.load_extension(ext)
                    self._name = "sqlite-vec"
                    break
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            self._name = "json-blob"


def open_vector_index(db_path: Path | str, *, prefer_sqlite_vec: bool = True) -> VectorIndex:
    if prefer_sqlite_vec:
        return SqliteVecIndex(db_path)
    return JsonBlobVectorIndex(db_path)


def l2(vec: list[float]) -> float:
    return math.sqrt(sum(v * v for v in vec)) or 1.0
