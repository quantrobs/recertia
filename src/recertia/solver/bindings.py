"""Parameter / input binding and dependency-wave helpers for skill application (specs §26)."""

from __future__ import annotations

import re

from contracts.resources import ResourceClaim
from contracts.skill import InputBinding, Step, step_dependencies
from recertia.solver.claims import ClaimScheduler

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


def bind_parameters(template: str, params: dict[str, object]) -> str:
    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            return match.group(0)
        return str(params[name])

    return _PLACEHOLDER.sub(repl, template)


def bind_inputs(
    inputs: dict,
    params: dict[str, object],
    bindings: list[InputBinding] | None = None,
    step_outputs: dict[tuple[str, str], object] | None = None,
) -> dict:
    out: dict = {}
    for k, v in inputs.items():
        if isinstance(v, str):
            out[k] = bind_parameters(v, params)
        else:
            out[k] = v
    for binding in bindings or []:
        input_name = binding.input
        output_key = (binding.source_step, binding.output)
        if step_outputs is None or output_key not in step_outputs:
            raise ValueError(f"missing bound output {output_key[0]}.{output_key[1]}")
        out[input_name] = step_outputs[output_key]
    return out


def topological_waves(steps: list[Step], max_parallel: int) -> list[list[Step]]:
    """Compute dependency waves ignoring claims (claims are resolved at dispatch time)."""

    remaining = {s.id: s for s in steps}
    done: set[str] = set()
    waves: list[list[Step]] = []
    while remaining:
        ready = [
            s
            for s in remaining.values()
            if all(d in done for d in step_dependencies(s))
        ]
        if not ready:
            raise ValueError("step graph has a cycle or unsatisfied input binding at runtime")
        # Claim-aware packing happens in the applicator; here we just batch by dependency.
        wave = ready[:max_parallel]
        waves.append(wave)
        for s in wave:
            done.add(s.id)
            del remaining[s.id]
    return waves


def claims_conflict(a: list[ResourceClaim], b: list[ResourceClaim]) -> bool:
    for ca in a:
        for cb in b:
            if ClaimScheduler.conflicts_with(ca, cb):
                return True
    return False
