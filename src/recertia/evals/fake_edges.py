"""Fake-edge accounting from typed ``input_bindings`` + run transcripts (S1 / specs §26.1).

An edge is data-carrying only when a later step actually consumes a named predecessor
output. With bindings as the sole authoring form, the remaining check is semantic: given
a transcript, did each bound output appear as both produced and consumed?
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from contracts.skill import InputBinding, SkillVersion, step_dependencies


@dataclass(frozen=True)
class BoundOutput:
    """One declared consumer binding onto a predecessor output."""

    consumer_step: str
    binding: InputBinding

    @property
    def source_step(self) -> str:
        return self.binding.source_step

    @property
    def output(self) -> str:
        return self.binding.output

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.consumer_step, self.source_step, self.output)


def iter_bound_outputs(skill: SkillVersion) -> list[BoundOutput]:
    """Return every input binding as a bound-output edge."""

    edges: list[BoundOutput] = []
    for step in skill.steps:
        for binding in step.input_bindings:
            edges.append(BoundOutput(consumer_step=step.id, binding=binding))
    return edges


def _events(transcript: dict[str, Any] | Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(transcript, dict):
        raw = transcript.get("events", [])
    else:
        raw = list(transcript)
    out: list[dict[str, Any]] = []
    for event in raw:
        if not isinstance(event, dict):
            continue
        kind = event.get("kind")
        payload = event.get("payload", event)
        if not isinstance(payload, dict):
            payload = {}
        out.append({"kind": kind, "payload": payload})
    return out


def produced_outputs(events: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    """``(step_id, output_name)`` pairs recorded as ``step_output``."""

    found: set[tuple[str, str]] = set()
    for event in events:
        if event.get("kind") != "step_output":
            continue
        payload = event.get("payload") or {}
        step_id = payload.get("step_id")
        name = payload.get("output")
        if isinstance(step_id, str) and isinstance(name, str):
            found.add((step_id, name))
    return found


def consumed_bindings(events: Iterable[dict[str, Any]]) -> set[tuple[str, str, str]]:
    """``(consumer_step, source_step, output)`` triples seen on ``step_start``."""

    found: set[tuple[str, str, str]] = set()
    for event in events:
        if event.get("kind") != "step_start":
            continue
        payload = event.get("payload") or {}
        consumer = payload.get("step_id")
        if not isinstance(consumer, str):
            continue
        for binding in payload.get("input_bindings") or []:
            if not isinstance(binding, dict):
                continue
            source = binding.get("source_step")
            output = binding.get("output")
            if isinstance(source, str) and isinstance(output, str):
                found.add((consumer, source, output))
    return found


def ran_steps(events: Iterable[dict[str, Any]]) -> set[str]:
    """Step ids that appear on a ``step_start`` event (actually executed this run)."""

    found: set[str] = set()
    for event in events:
        if event.get("kind") != "step_start":
            continue
        payload = event.get("payload") or {}
        step_id = payload.get("step_id")
        if isinstance(step_id, str):
            found.add(step_id)
    return found


def unused_bound_outputs(
    skill: SkillVersion,
    transcript: dict[str, Any] | Sequence[dict[str, Any]],
) -> list[BoundOutput]:
    """Bound outputs that ran on both ends but never carried produced+consumed data.

    Partial transcripts (producer or consumer never started) are not scored — they must
    not accumulate as fake-edge failures for ``propose_parallelise``.
    """

    events = _events(transcript)
    produced = produced_outputs(events)
    consumed = consumed_bindings(events)
    started = ran_steps(events)
    unused: list[BoundOutput] = []
    for edge in iter_bound_outputs(skill):
        if edge.source_step not in started or edge.consumer_step not in started:
            continue
        produced_ok = (edge.source_step, edge.output) in produced
        consumed_ok = edge.key in consumed
        if not (produced_ok and consumed_ok):
            unused.append(edge)
    return unused


def fake_edge_checks(
    skill: SkillVersion,
    transcript: dict[str, Any] | Sequence[dict[str, Any]],
) -> list[bool]:
    """Per scored binding: ``True`` when the edge carried data this run, else ``False``.

    Bindings whose producer or consumer never ran are omitted (not a failure).
    Empty skill bindings yield an empty list (rate 0 downstream).
    """

    events = _events(transcript)
    started = ran_steps(events)
    unused = {edge.key for edge in unused_bound_outputs(skill, transcript)}
    scored = [
        edge
        for edge in iter_bound_outputs(skill)
        if edge.source_step in started and edge.consumer_step in started
    ]
    return [edge.key not in unused for edge in scored]


def fake_edge_failure_count(
    skill: SkillVersion,
    transcripts: Sequence[dict[str, Any] | Sequence[dict[str, Any]]],
) -> int:
    """Count binding-level fake-edge failures across run transcripts."""

    total = 0
    for transcript in transcripts:
        total += sum(1 for ok in fake_edge_checks(skill, transcript) if not ok)
    return total


def binding_failure_counts(
    skill: SkillVersion,
    transcripts: Sequence[dict[str, Any] | Sequence[dict[str, Any]]],
) -> dict[tuple[str, str, str], int]:
    """Per-edge fake counts keyed by ``(consumer, source, output)``."""

    counts: dict[tuple[str, str, str], int] = {
        edge.key: 0 for edge in iter_bound_outputs(skill)
    }
    for transcript in transcripts:
        for edge in unused_bound_outputs(skill, transcript):
            counts[edge.key] = counts.get(edge.key, 0) + 1
    return counts


def edges_failing_threshold(
    skill: SkillVersion,
    transcripts: Sequence[dict[str, Any] | Sequence[dict[str, Any]]],
    *,
    threshold: int = 5,
) -> list[BoundOutput]:
    """Bindings that failed the fake-edge test on at least ``threshold`` runs."""

    counts = binding_failure_counts(skill, transcripts)
    by_key = {edge.key: edge for edge in iter_bound_outputs(skill)}
    return [by_key[key] for key, n in counts.items() if n >= threshold and key in by_key]


def declared_edge_count(skill: SkillVersion) -> int:
    """Number of declared dependency edges implied by input bindings."""

    return sum(len(step_dependencies(step)) for step in skill.steps)
