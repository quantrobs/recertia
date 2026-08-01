"""Solver package: model client, tool runtime, transcripts, skill application (M2)."""

from recertia.solver.apply import SkillApplicator, WaveResult
from recertia.solver.model import ModelClient, ModelResponse, StubModelClient
from recertia.solver.tools import SideEffectClass, Tool, ToolRegistry, ToolResult, ToolRuntime
from recertia.solver.transcript import TranscriptStore, TranscriptWriter

__all__ = [
    "ModelClient",
    "ModelResponse",
    "StubModelClient",
    "SideEffectClass",
    "Tool",
    "ToolRegistry",
    "ToolRuntime",
    "ToolResult",
    "TranscriptStore",
    "TranscriptWriter",
    "SkillApplicator",
    "WaveResult",
]
