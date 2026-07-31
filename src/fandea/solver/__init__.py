"""Solver package: model client, tool runtime, transcripts, skill application (M2)."""

from fandea.solver.apply import SkillApplicator, WaveResult
from fandea.solver.model import ModelClient, ModelResponse, StubModelClient
from fandea.solver.tools import SideEffectClass, Tool, ToolRegistry, ToolResult, ToolRuntime
from fandea.solver.transcript import TranscriptStore, TranscriptWriter

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
