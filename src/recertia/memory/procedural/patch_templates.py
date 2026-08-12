"""O(1) patch-template store. User evolve does a point get; it does not search."""

from __future__ import annotations

from pathlib import Path

from contracts.patch import PatchTemplate


class PatchTemplateStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, failure_signature: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in failure_signature)
        return self.root / f"{safe[:180]}.json"

    def publish(self, template: PatchTemplate) -> Path:
        dest = self._path(template.failure_signature)
        dest.write_text(template.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return dest

    def get(self, failure_signature: str) -> PatchTemplate | None:
        dest = self._path(failure_signature)
        if not dest.exists():
            return None
        return PatchTemplate.model_validate_json(dest.read_text(encoding="utf-8"))
