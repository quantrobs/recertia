"""Compatibility re-export for :func:`script_from_skill`.

Prefer :mod:`recertia.memory.procedural.script` for new imports.
"""

from __future__ import annotations

from recertia.memory.procedural.script import script_from_skill

__all__ = ["script_from_skill"]
