"""Content-addressed structured transcript writer (M2)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class TranscriptEvent:
    kind: str  # step_start | step_end | wave | model | tool | note
    at: str
    payload: dict = field(default_factory=dict)


@dataclass
class Transcript:
    run_id: str
    attempt_no: int
    events: list[TranscriptEvent] = field(default_factory=list)
    content_hash: str | None = None

    def append(self, kind: str, **payload: object) -> None:
        self.events.append(
            TranscriptEvent(
                kind=kind,
                at=datetime.now(timezone.utc).isoformat(),
                payload=dict(payload),
            )
        )


class TranscriptStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, content_hash: str) -> Path:
        return self.root / content_hash[:2] / f"{content_hash}.json"

    def write(self, transcript: Transcript) -> str:
        payload = {
            "run_id": transcript.run_id,
            "attempt_no": transcript.attempt_no,
            "events": [asdict(e) for e in transcript.events],
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        content_hash = hashlib.sha256(blob).hexdigest()
        dest = self.path_for(content_hash)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            # Write via temp+rename for atomicity; content-addressed so identical is a no-op.
            tmp = dest.with_suffix(".tmp")
            tmp.write_bytes(blob)
            tmp.replace(dest)
        transcript.content_hash = content_hash
        return content_hash

    def read(self, content_hash: str) -> dict:
        return json.loads(self.path_for(content_hash).read_text(encoding="utf-8"))


class TranscriptWriter:
    """Convenience wrapper bound to one attempt."""

    def __init__(self, store: TranscriptStore, run_id: str, attempt_no: int) -> None:
        self.store = store
        self.transcript = Transcript(run_id=run_id, attempt_no=attempt_no)

    def event(self, kind: str, **payload: object) -> None:
        self.transcript.append(kind, **payload)

    def finalize(self) -> str:
        return self.store.write(self.transcript)
