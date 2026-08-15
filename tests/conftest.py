"""Explicit test-only execution capability for integration fixtures.

Production defaults to the Docker/Podman backend.  Tests opt into the bounded
local executor before importing or constructing orchestration services.
"""

from __future__ import annotations

import os

os.environ.setdefault("RECERTIA_EXECUTION_BACKEND", "local")
# Tests exercise the HTTP API against the local backend; production API refuses local
# unless this break-glass flag is set.
os.environ.setdefault("RECERTIA_API_ALLOW_LOCAL_EXEC", "1")
# CI / non-Windows hosts: allow POSIX absolute registered roots (RW0 tests).
os.environ.setdefault("RECERTIA_ALLOW_POSIX_WORKSPACE_ROOTS", "1")
