"""Unit tests for claim scheduling basics."""

from __future__ import annotations

import threading
import time

import pytest

from contracts.resources import ResourceClaim
from recertia.solver.claims import ClaimScheduler, ClaimTimeoutError
from recertia.solver.tools import ClaimScheduler as ToolsClaimScheduler


def test_conflicts_with_modes() -> None:
    a = ResourceClaim(kind="file", id="f", mode="read")
    b = ResourceClaim(kind="file", id="f", mode="write")
    c = ResourceClaim(kind="file", id="g", mode="write")
    assert ClaimScheduler.conflicts_with(a, a) is False
    assert ClaimScheduler.conflicts_with(a, b) is True
    assert ClaimScheduler.conflicts_with(a, c) is False
    assert ToolsClaimScheduler is ClaimScheduler


def test_acquire_and_release_same_claim() -> None:
    scheduler = ClaimScheduler(claim_timeout_s=1.0)
    claim = ResourceClaim(kind="file", id="lock", mode="exclusive")
    scheduler.acquire("step-a", [claim])
    assert scheduler.held_by() == {("file", "lock"): "step-a"}
    scheduler.release("step-a", [claim])
    assert scheduler.held_by() == {}


def test_claim_timeout_raises() -> None:
    scheduler = ClaimScheduler(claim_timeout_s=0.05)
    claim = ResourceClaim(kind="file", id="hot", mode="write")
    scheduler.acquire("holder", [claim])

    def contender() -> None:
        with pytest.raises(ClaimTimeoutError) as excinfo:
            scheduler.acquire("waiter", [claim])
        assert excinfo.value.conflict.resolution == "timed_out"
        assert excinfo.value.conflict.waiting == "waiter"

    thread = threading.Thread(target=contender)
    thread.start()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    # Give the contender a moment; holder still owns the claim.
    time.sleep(0.01)
    assert scheduler.held_by()[("file", "hot")] == "holder"
    scheduler.release("holder", [claim])
