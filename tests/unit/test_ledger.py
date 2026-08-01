from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from recertia.ledger import HashChainLedger, LedgerVerificationError


def test_append_and_verify_empty_ledger(tmp_path: Path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    ledger.verify()  # empty chain is trivially valid


def test_append_chains_hashes(tmp_path: Path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    e1 = ledger.append(actor="a", action="write", target="skill-1", at=datetime.now(timezone.utc))
    e2 = ledger.append(
        actor="a",
        action="advance_to_candidate",
        target="skill-1",
        at=datetime.now(timezone.utc),
    )

    assert e1.seq == 0
    assert e2.seq == 1
    assert e2.prev_hash == e1.entry_hash
    ledger.verify()


def test_tampering_an_entry_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = HashChainLedger(path)
    ledger.append(actor="a", action="write", target="skill-1", at=datetime.now(timezone.utc))
    ledger.append(
        actor="a",
        action="advance_to_candidate",
        target="skill-1",
        at=datetime.now(timezone.utc),
    )

    lines = path.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["target"] = "skill-9-attacker-controlled"
    lines[0] = json.dumps(tampered)
    path.write_text("\n".join(lines) + "\n")

    tampered_ledger = HashChainLedger(path)
    with pytest.raises(LedgerVerificationError):
        tampered_ledger.verify()


def test_broken_chain_link_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = HashChainLedger(path)
    ledger.append(actor="a", action="write", target="skill-1", at=datetime.now(timezone.utc))
    ledger.append(actor="a", action="write", target="skill-2", at=datetime.now(timezone.utc))

    lines = path.read_text().splitlines()
    e0 = json.loads(lines[0])
    e0["prev_hash"] = "f" * 64
    lines[0] = json.dumps(e0)
    path.write_text("\n".join(lines) + "\n")

    with pytest.raises(LedgerVerificationError):
        HashChainLedger(path).verify()


def test_tip_hash_tracks_the_last_entry(tmp_path: Path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    assert ledger.tip_hash() == "0" * 64
    e1 = ledger.append(actor="a", action="write", target="x", at=datetime.now(timezone.utc))
    assert ledger.tip_hash() == e1.entry_hash
