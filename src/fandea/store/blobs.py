"""Content-addressed blob store (transcripts/snapshots); disk now, S3-shaped API later."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol


class BlobStore(Protocol):
    def put(self, data: bytes, *, content_type: str = "application/octet-stream") -> str: ...

    def get(self, digest: str) -> bytes: ...

    def exists(self, digest: str) -> bool: ...


class FilesystemBlobStore:
    """``blobs/ab/abcd…`` layout; key is ``sha256:<hex>``."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        hexdig = digest.removeprefix("sha256:")
        return self.root / hexdig[:2] / hexdig

    def put(self, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        path = self._path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
            (path.parent / (path.name + ".type")).write_text(content_type, encoding="utf-8")
        return digest

    def get(self, digest: str) -> bytes:
        path = self._path(digest)
        if not path.exists():
            raise FileNotFoundError(digest)
        return path.read_bytes()

    def exists(self, digest: str) -> bool:
        return self._path(digest).exists()
