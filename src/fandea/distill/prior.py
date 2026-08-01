"""Load the versioned authoring prior (T2)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from contracts.policy import AuthoringPrior

_DEFAULT = Path(__file__).resolve().parents[3] / "policy" / "authoring-prior.json"


@lru_cache(maxsize=4)
def load_authoring_prior(path: str | None = None) -> AuthoringPrior:
    target = Path(path) if path else _DEFAULT
    data = json.loads(target.read_text(encoding="utf-8"))
    return AuthoringPrior.model_validate(data)
