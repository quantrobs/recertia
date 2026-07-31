"""Hash-chain mechanics for the provenance ledger (specs §21).

Storage is an append-only JSONL file: one ``LedgerEntry`` per line, in ``seq`` order. This is
the M0-minimal persistence — durable across process restarts, trivially diffable, and exactly
as much mechanism as ``fandea ledger verify`` needs. A SQLite/Postgres-backed store (per the
tech stack in ``docs/implementation-plan.md``) can replace this later without changing
``LedgerEntry`` itself, since the contract lives in ``contracts/ledger.py``, not here.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from contracts.ledger import LedgerAction, LedgerEntry

GENESIS_HASH = "0" * 64


class LedgerVerificationError(Exception):
    """The chain does not verify: a hash mismatch, a broken link, or a gap in ``seq``."""


def _canonical_bytes(entry: LedgerEntry) -> bytes:
    """Canonical serialisation of every field except ``entry_hash`` (specs §21)."""

    payload = entry.model_dump(mode="json", exclude={"entry_hash"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_entry_hash(entry: LedgerEntry) -> str:
    return hashlib.sha256(_canonical_bytes(entry)).hexdigest()


class HashChainLedger:
    """One ledger, backed by one append-only JSONL file.

    Thread-safe within a process via a lock; safe across process restarts because every
    ``append`` is a single atomic line write and ``verify`` recomputes the whole chain from
    disk rather than trusting in-memory state.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _read_all(self) -> list[LedgerEntry]:
        if not self._path.exists():
            return []
        entries: list[LedgerEntry] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(LedgerEntry.model_validate_json(line))
        return entries

    def tip_hash(self) -> str:
        entries = self._read_all()
        return entries[-1].entry_hash if entries else GENESIS_HASH

    def append(
        self,
        *,
        actor: str,
        action: LedgerAction,
        target: str,
        evidence: dict | None = None,
        at: datetime | None = None,
    ) -> LedgerEntry:
        """Append one entry. Returns the entry as written, with ``seq`` and hashes filled in."""

        with self._lock:
            existing = self._read_all()
            seq = len(existing)
            prev_hash = existing[-1].entry_hash if existing else GENESIS_HASH
            draft = LedgerEntry(
                seq=seq,
                prev_hash=prev_hash,
                entry_hash="pending",
                actor=actor,
                action=action,
                target=target,
                evidence=evidence or {},
                at=at or datetime.now(timezone.utc),
            )
            entry = draft.model_copy(update={"entry_hash": compute_entry_hash(draft)})
            with self._path.open("a", encoding="utf-8") as f:
                f.write(entry.model_dump_json() + "\n")
            return entry

    def entries(self) -> list[LedgerEntry]:
        return self._read_all()

    def verify(self) -> None:
        """Recompute the whole chain; raise :class:`LedgerVerificationError` on the first break.

        Mirrors ``GET /v1/ledger/verify`` (specs §21): every entry's ``entry_hash`` must
        recompute correctly, every ``seq`` must be contiguous from 0, and every ``prev_hash``
        must equal the predecessor's ``entry_hash``.
        """

        entries = self._read_all()
        prev_hash = GENESIS_HASH
        for i, entry in enumerate(entries):
            if entry.seq != i:
                raise LedgerVerificationError(f"entry at position {i} has seq={entry.seq}, expected {i}")
            if entry.prev_hash != prev_hash:
                raise LedgerVerificationError(
                    f"entry seq={entry.seq} has prev_hash={entry.prev_hash!r}, "
                    f"expected {prev_hash!r} (chain broken)"
                )
            draft = entry.model_copy(update={"entry_hash": "pending"})
            recomputed = compute_entry_hash(draft)
            if recomputed != entry.entry_hash:
                raise LedgerVerificationError(
                    f"entry seq={entry.seq} entry_hash={entry.entry_hash!r} does not match "
                    f"recomputed {recomputed!r} (tampered or corrupted)"
                )
            prev_hash = entry.entry_hash
