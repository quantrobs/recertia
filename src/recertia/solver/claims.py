"""Fixed-order resource claim acquisition with timeout → merge/serialise (specs §26.2)."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence

from contracts.resources import ResourceClaim, ResourceConflict


class ClaimTimeoutError(Exception):
    def __init__(self, conflict: ResourceConflict) -> None:
        self.conflict = conflict
        super().__init__(
            f"claim timeout: {conflict.waiting} waited {conflict.waited_ms}ms for "
            f"{conflict.claim.kind}:{conflict.claim.id} held by {conflict.holder}"
        )


class ClaimScheduler:
    """Fixed-order claim acquisition with timeout → merge/serialise signal (specs §26.2)."""

    def __init__(self, claim_timeout_s: float = 60.0) -> None:
        self.claim_timeout_s = claim_timeout_s
        self._holders: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()
        # Waiters block on this condition instead of a 1ms sleep-poll loop: releases
        # wake contenders immediately, which both lowers latency and stops the spin.
        self._cond = threading.Condition(self._lock)
        self._conflicts: list[ResourceConflict] = []

    @property
    def conflicts(self) -> Sequence[ResourceConflict]:
        """Read-only view of observed claim waits and timeouts."""

        return tuple(self._conflicts)

    @staticmethod
    def sort_key(claim: ResourceClaim) -> tuple[str, str]:
        return (claim.kind, claim.id)

    @staticmethod
    def conflicts_with(a: ResourceClaim, b: ResourceClaim) -> bool:
        if a.kind != b.kind or a.id != b.id:
            return False
        return a.mode in ("write", "exclusive") or b.mode in ("write", "exclusive")

    def acquire(self, step_id: str, claims: list[ResourceClaim]) -> list[ResourceConflict]:
        """Acquire all claims for ``step_id`` in global order. Raises :class:`ClaimTimeoutError`."""

        ordered = sorted(claims, key=self.sort_key)
        acquired: list[ResourceClaim] = []
        waits: list[ResourceConflict] = []
        started = time.monotonic()
        deadline = started + self.claim_timeout_s
        with self._cond:
            for claim in ordered:
                key = (claim.kind, claim.id)
                while True:
                    holder = self._holders.get(key)
                    if holder is None or holder == step_id:
                        self._holders[key] = step_id
                        acquired.append(claim)
                        waited_ms = int((time.monotonic() - started) * 1000)
                        if waited_ms > 0:
                            conflict = ResourceConflict(
                                claim=claim,
                                waiting=step_id,
                                holder=holder or "none",
                                waited_ms=waited_ms,
                                resolution="acquired",
                            )
                            waits.append(conflict)
                            self._conflicts.append(conflict)
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        waited_ms = int((time.monotonic() - started) * 1000)
                        conflict = ResourceConflict(
                            claim=claim,
                            waiting=step_id,
                            holder=holder or "unknown",
                            waited_ms=waited_ms,
                            resolution="timed_out",
                        )
                        self._conflicts.append(conflict)
                        self._release_unlocked(step_id, acquired)
                        self._cond.notify_all()
                        raise ClaimTimeoutError(conflict)
                    self._cond.wait(timeout=remaining)
        return waits

    def _release_unlocked(self, step_id: str, claims: list[ResourceClaim]) -> None:
        for claim in claims:
            key = (claim.kind, claim.id)
            if self._holders.get(key) == step_id:
                del self._holders[key]

    def release(self, step_id: str, claims: list[ResourceClaim]) -> None:
        with self._cond:
            self._release_unlocked(step_id, claims)
            self._cond.notify_all()

    def held_by(self) -> dict[tuple[str, str], str]:
        with self._lock:
            return dict(self._holders)
