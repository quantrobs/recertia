"""Derive an M1 scripted attempt from a SkillVersion's shell steps."""

from __future__ import annotations

from contracts.skill import SkillVersion, step_dependencies


def script_from_skill(version: SkillVersion) -> list[str]:
    """Topological shell-step script; non-shell tools become no-op markers (tool runtime is M2)."""

    script: list[str] = []
    remaining = {s.id: s for s in version.steps}
    done: set[str] = set()
    while remaining:
        progress = False
        for sid, step in list(remaining.items()):
            if all(d in done for d in step_dependencies(step)):
                if step.tool == "shell" and "command" in step.inputs:
                    script.append(str(step.inputs["command"]))
                else:
                    script.append(f"true  # step={step.id} tool={step.tool or 'none'}")
                done.add(sid)
                del remaining[sid]
                progress = True
        if not progress:
            break
    return script or ["true"]
