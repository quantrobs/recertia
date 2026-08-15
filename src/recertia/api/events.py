"""Per-run event log + SSE helpers (console C2)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


class RunEventLog:
    """Append-only JSONL events under ``{runs_root}/events/{run_id}.jsonl``."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, run_id: str) -> Path:
        safe = run_id.replace("/", "_").replace("..", "_")
        return self.root / f"{safe}.jsonl"

    def append(self, run_id: str, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {
            "event_id": uuid4().hex[:16],
            "run_id": run_id,
            "type": event_type,
            "at": datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        }
        with self._lock:
            path = self._path(run_id)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, separators=(",", ":")) + "\n")
        return event

    def list_after(self, run_id: str, *, after: str | None = None) -> list[dict[str, Any]]:
        path = self._path(run_id)
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        seen_after = after is None
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                if not seen_after:
                    if event.get("event_id") == after:
                        seen_after = True
                    continue
                out.append(event)
        return out

    def iter_sse(self, run_id: str, *, after: str | None = None) -> Iterator[str]:
        """Yield SSE chunks for current backlog (caller may poll again)."""

        events = self.list_after(run_id, after=after)
        last_id = after
        for event in events:
            last_id = event["event_id"]
            yield f"id: {event['event_id']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"
        if last_id:
            yield f": cursor {last_id}\n\n"
