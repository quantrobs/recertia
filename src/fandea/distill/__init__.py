"""Distillation package: success path, failure clusters, reusability, authoring prior."""

from fandea.distill.prior import load_authoring_prior
from fandea.distill.reusability import assess_reusability

__all__ = ["assess_reusability", "load_authoring_prior"]
