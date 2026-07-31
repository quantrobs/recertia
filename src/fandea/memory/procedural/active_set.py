"""Active-set stub (M1; refactor-plan B6 / specs §24.1).

M5 will cap, rank, and evict. M1 only installs the *filter* retrieval already depends on:
every ``approved`` version enters the active set (``active=True``) by default. Retrieval
drops anything with ``active=False``, so M5 tightens a working gate instead of installing the
first one.
"""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.common import RETRIEVABLE_LIFECYCLES
from contracts.status import SkillStatus
from fandea.memory.procedural.store import SkillStore


def assign_active_on_approval(status: SkillStatus) -> SkillStatus:
    """Return a copy with ``active=True`` iff lifecycle is in the retrievable set.

    Call this at the moment a version transitions to ``approved`` (or ``shadow``). Shadow
    stays ``active=False`` for direct application — ``is_retrievable`` requires approved AND
    active — but shadow remains visible to the retrieval filter's lifecycle check for
    comparison runs (specs §2.2).
    """

    if status.lifecycle == "approved":
        return status.model_copy(update={"active": True})
    if status.lifecycle in RETRIEVABLE_LIFECYCLES:
        # shadow: retrievable for comparison only; not in the application active set
        return status.model_copy(update={"active": False})
    return status.model_copy(update={"active": False})


def recompute_active_set(store: SkillStore) -> list[SkillStatus]:
    """M1 stub: every approved version is active; everything else is not.

    Returns the updated status records (also written back to the store).
    """

    updated: list[SkillStatus] = []
    for _version, status, _stats in store.iter_loaded():
        new_status = assign_active_on_approval(status)
        if new_status != status:
            store.write_status(new_status)
            updated.append(new_status)
        else:
            updated.append(status)
    return updated


def now() -> datetime:
    return datetime.now(timezone.utc)
