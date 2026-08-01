"""Small helpers shared by node implementations. Not part of the public API."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from contracts.criteria import TaskCriterion


def now() -> datetime:
    return datetime.now(timezone.utc)


def criteria_hash(criteria: list[TaskCriterion]) -> str:
    """sha256 of the locked ``TaskCriterion`` set's canonical serialisation (specs §15.1)."""

    payload = [c.model_dump(mode="json") for c in criteria]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
