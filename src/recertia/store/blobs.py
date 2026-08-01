"""Content-addressed blob store (transcripts/snapshots); disk now, S3-shaped API later."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Protocol

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class BlobStore(Protocol):
    def put(self, data: bytes, *, content_type: str = "application/octet-stream") -> str: ...

    def get(self, digest: str) -> bytes: ...

    def exists(self, digest: str) -> bool: ...


def normalize_blob_digest(digest: str) -> str:
    """Require ``sha256:`` + 64 lowercase hex; reject traversal / absolute forms."""

    key = digest if digest.startswith("sha256:") else f"sha256:{digest}"
    if not _DIGEST_RE.fullmatch(key):
        raise ValueError(f"invalid blob digest: {digest!r}")
    return key


class FilesystemBlobStore:
    """``blobs/ab/abcd…`` layout; key is ``sha256:<hex>``."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        key = normalize_blob_digest(digest)
        hexdig = key.removeprefix("sha256:")
        root = self.root.resolve()
        path = (root / hexdig[:2] / hexdig).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise FileNotFoundError(digest) from exc
        return path

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
        try:
            return self._path(digest).exists()
        except (ValueError, FileNotFoundError):
            return False
