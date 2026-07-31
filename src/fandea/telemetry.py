"""OpenTelemetry-shaped spans and required operational events (M9 hardening).

Uses the OpenTelemetry API when installed; otherwise an in-process recorder so CI and local
runs stay dependency-light while still asserting the required event surface.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

REQUIRED_EVENTS = frozenset(
    {
        "run.started",
        "run.finished",
        "node.started",
        "node.finished",
        "tool.invoked",
        "judge.context.opened",
        "merge.audited",
        "policy.changed",
        "scope.promoted",
    }
)


@dataclass
class SpanEvent:
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SpanRecord:
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[SpanEvent] = field(default_factory=list)
    status: str = "ok"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None


class Telemetry:
    """Process-local span/event recorder (OTel-compatible surface)."""

    def __init__(self) -> None:
        self.spans: list[SpanRecord] = []
        self.events: list[SpanEvent] = []
        self._otel = None
        try:
            from opentelemetry import trace  # type: ignore

            self._otel = trace.get_tracer("fandea")
        except Exception:  # noqa: BLE001 — optional dependency
            self._otel = None

    def emit(self, name: str, **attributes: Any) -> SpanEvent:
        event = SpanEvent(name=name, attributes=attributes)
        self.events.append(event)
        return event

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[SpanRecord]:
        record = SpanRecord(name=name, attributes=attributes)
        self.spans.append(record)
        otel_cm = None
        if self._otel is not None:
            otel_cm = self._otel.start_as_current_span(name)
            otel_cm.__enter__()
        try:
            yield record
        except Exception:
            record.status = "error"
            raise
        finally:
            record.ended_at = datetime.now(timezone.utc)
            if otel_cm is not None:
                otel_cm.__exit__(None, None, None)

    def missing_required(self) -> list[str]:
        seen = {e.name for e in self.events}
        return sorted(REQUIRED_EVENTS - seen)


_GLOBAL = Telemetry()


def get_telemetry() -> Telemetry:
    return _GLOBAL


def reset_telemetry() -> Telemetry:
    global _GLOBAL
    _GLOBAL = Telemetry()
    return _GLOBAL
