"""T3 sandbox policy (ADR-0005). Mutable only via human review — never by runs/jobs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SandboxPolicy:
    """Process-isolation and approval thresholds for non-read tools."""

    require_approval_for_non_read: bool = True
    allow_network: bool = False
    max_cpu_seconds: int = 60
    max_address_space_mb: int = 512
    scrub_env: bool = True
    allowed_env_keys: tuple[str, ...] = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
    # Container backend name; ``subprocess`` is the default local jail.
    backend: str = "subprocess"
    image: str | None = None  # set when backend == "container"


DEFAULT_SANDBOX = SandboxPolicy()


@dataclass
class ApprovalRecord:
    tool: str
    step_id: str
    actor: str
    reason: str = ""


@dataclass
class ApprovalGate:
    """Allowlist of approved (tool, step) or tool-wide grants for one run."""

    grants: set[tuple[str, str | None]] = field(default_factory=set)
    records: list[ApprovalRecord] = field(default_factory=list)

    def approve(
        self,
        tool: str,
        *,
        step_id: str | None = None,
        actor: str = "operator",
        reason: str = "",
    ) -> None:
        self.grants.add((tool, step_id))
        self.records.append(
            ApprovalRecord(tool=tool, step_id=step_id or "*", actor=actor, reason=reason)
        )

    def is_approved(self, tool: str, step_id: str) -> bool:
        return (tool, step_id) in self.grants or (tool, None) in self.grants
