"""Compatibility re-export for :func:`script_from_skill`.

Prefer :mod:`fandea.memory.procedural.script` for new imports.
"""

from __future__ import annotations

from fandea.memory.procedural.script import script_from_skill

__all__ = ["script_from_skill"]
