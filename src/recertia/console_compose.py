"""Pilot Compose: draft Goal criteria from intent (AI propose → human accept).

Drafts are never locked. Callers must apply drafts to a Goal form, run
``compile_goal`` / ``POST /v1/goals/preview``, then submit. ADR-0003 / ADR-0010.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from contracts.goal import DesiredState, Goal

DraftSource = Literal["heuristic", "model", "template"]


@dataclass
class DraftDesired:
    id: str
    kind: str
    path: str | None = None
    pattern: str | None = None
    run: str | None = None
    weight: float = 1.0
    why: str = ""
    risk: str = ""
    selected: bool = True

    def to_desired_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "weight": self.weight,
        }
        if self.path is not None:
            out["path"] = self.path
        if self.pattern is not None:
            out["pattern"] = self.pattern
        if self.run is not None:
            out["run"] = self.run
        return out


@dataclass
class DraftConstraint:
    id: str
    kind: str
    value: str | float | list[str]
    why: str = ""
    selected: bool = True

    def to_constraint_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "value": self.value,
            "weight": 1.0,
        }


@dataclass
class StressWarning:
    code: str
    message: str
    severity: Literal["info", "warn", "block"] = "warn"


@dataclass
class GoalPackItem:
    title: str
    context: str
    desired: list[DraftDesired] = field(default_factory=list)
    constraints: list[DraftConstraint] = field(default_factory=list)


@dataclass
class SuggestResult:
    source: DraftSource
    context: str
    task_class: str
    desired: list[DraftDesired]
    constraints: list[DraftConstraint]
    warnings: list[StressWarning]
    pack: list[GoalPackItem] = field(default_factory=list)
    disclaimer: str = (
        "AI/heuristic draft only — you confirm before preview/submit. "
        "Success criteria are never auto-locked from this response."
    )

    def to_dict(self) -> dict[str, Any]:
        pack_payload = [
            {
                "title": p.title,
                "context": p.context,
                "desired": [asdict(d) for d in p.desired],
                "constraints": [asdict(c) for c in p.constraints],
            }
            for p in self.pack
        ]
        decompositions: list[dict[str, Any]] = []
        if self.pack:
            decompositions.append(
                {
                    "decomposition": "by_risk",
                    "rationale": "Characterize → mutate → lock (from Compose pack draft)",
                    "steps": [
                        {
                            "title": p["title"],
                            "context": p["context"],
                            "desired": p["desired"],
                            "constraints": p["constraints"],
                            "freeze_paths": [],
                            "mutate_paths": [],
                            "role": (
                                "characterization"
                                if i == 0
                                else ("behaviour_lock" if i == len(pack_payload) - 1 else "structural")
                            ),
                        }
                        for i, p in enumerate(pack_payload)
                    ],
                }
            )
            # Alternate seam-shaped decomposition (same steps, different label)
            decompositions.append(
                {
                    "decomposition": "by_seam",
                    "rationale": "Same phases framed as a single seam sequence",
                    "steps": list(decompositions[0]["steps"]),
                }
            )
        return {
            "source": self.source,
            "context": self.context,
            "task_class": self.task_class,
            "desired": [asdict(d) for d in self.desired],
            "constraints": [asdict(c) for c in self.constraints],
            "warnings": [asdict(w) for w in self.warnings],
            "pack": pack_payload,
            "decompositions": decompositions,
            "disclaimer": self.disclaimer,
        }


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def heuristic_suggest(*, context: str, task_class: str = "repo-chore") -> SuggestResult:
    """Keyword / pattern drafts that work offline without a model."""

    ctx = _norm(context)
    desired: list[DraftDesired] = []
    constraints: list[DraftConstraint] = []
    pack: list[GoalPackItem] = []

    def add_file(did: str, path: str, why: str, risk: str = "") -> None:
        desired.append(
            DraftDesired(
                id=did, kind="file_exists", path=path, why=why, risk=risk or "Path may already exist."
            )
        )

    def add_contains(did: str, path: str, pattern: str, why: str, risk: str = "") -> None:
        desired.append(
            DraftDesired(
                id=did,
                kind="file_contains",
                path=path,
                pattern=pattern,
                why=why,
                risk=risk or "Regex may be too loose or too strict.",
            )
        )

    def add_cmd(did: str, run: str, why: str, risk: str = "") -> None:
        desired.append(
            DraftDesired(
                id=did,
                kind="command",
                run=run,
                why=why,
                risk=risk or "Command may pass vacuously without the intended coverage.",
            )
        )

    # --- small chores ---
    if any(k in ctx for k in ("*.pyc", "pyc", "gitignore")):
        add_file("gitignore-exists", ".gitignore", "Ensure ignore file exists")
        add_contains(
            "pyc-ignored",
            ".gitignore",
            r"\*\.pyc",
            "Ignore compiled Python bytecode",
            "Pattern might not match existing ignore style",
        )

    if "editorconfig" in ctx or "editor config" in ctx:
        add_file("editorconfig-exists", ".editorconfig", "Root EditorConfig present")
        add_contains(
            "editorconfig-python",
            ".editorconfig",
            r"\[\*\.py\]",
            "Python indent section present",
        )

    if any(k in ctx for k in ("pytest.ini", "testpaths", "pytest config")):
        add_file("pytest-ini", "pytest.ini", "Pytest config file")
        add_contains(
            "testpaths",
            "pytest.ini",
            r"testpaths\s*=\s*tests",
            "Discover tests under tests/",
        )

    if any(k in ctx for k in ("python 3.12", "pin python", ".python-version", "python version")):
        add_file("python-version-file", ".python-version", "Pin runtime version file")
        add_contains(
            "python-312",
            ".python-version",
            r"^3\.12",
            "Pin exactly 3.12",
        )

    if any(k in ctx for k in ("github actions", "workflow", "ci.yml", "continuous integration")):
        add_file("ci-workflow", ".github/workflows/ci.yml", "CI workflow exists")
        add_contains(
            "ci-pytest",
            ".github/workflows/ci.yml",
            r"pytest",
            "CI runs pytest",
            "Workflow may invoke make/tox instead of bare pytest",
        )

    if "makefile" in ctx or "make ci" in ctx or "make test" in ctx:
        add_file("makefile", "Makefile", "Makefile present")
        add_contains("make-test", "Makefile", r"^test:", "test target defined")

    if "readme" in ctx and "testing" in ctx:
        add_contains(
            "readme-testing",
            "README.md",
            r"## Testing",
            "Document how to run tests",
        )

    # --- larger chores ---
    if "src/" in ctx or "src layout" in ctx or "package layout" in ctx:
        add_file("src-dir", "src", "src/ layout root")
        add_contains(
            "pyproject-packages",
            "pyproject.toml",
            r"packages\s*=|tool\.setuptools|tool\.hatch",
            "Packaging discovers src layout",
            "Exact packaging key varies by build backend",
        )
        add_cmd(
            "pytest-collects",
            "python -m pytest --collect-only -q",
            "Tests still collect after layout change",
            "Collect-only can pass with zero tests",
        )

    preserve = (
        "don't touch" in ctx
        or "do not touch" in ctx
        or "must not modify" in ctx
        or "leave application" in ctx
    )
    if preserve:
        constraints.append(
            DraftConstraint(
                id="no-touch-src",
                kind="must_not_modify",
                value=["src"],
                why="Context asked to preserve application source",
            )
        )

    # --- huge / pack ---
    huge = any(
        k in ctx
        for k in (
            "re-architect",
            "hexagonal",
            "monolith",
            "split the",
            "refactor the whole",
            "backward-compatible",
            "repository interface",
        )
    )
    large_split = any(k in ctx for k in ("split", "migrate", "re-architect", "hexagonal", "monolith"))

    if huge or (large_split and len(ctx) > 120):
        pack = [
            GoalPackItem(
                title="Inventory & guardrails",
                context="Capture baseline tests and forbid unrelated churn",
                desired=[
                    DraftDesired(
                        id="baseline-tests",
                        kind="command",
                        run="python -m pytest -q",
                        why="Baseline suite must already be runnable",
                        risk="Suite may be red before migration",
                    )
                ],
                constraints=[
                    DraftConstraint(
                        id="no-dep-bump",
                        kind="must_not_modify",
                        value=["poetry.lock", "uv.lock", "package-lock.json"],
                        why="Avoid dependency churn in the same Goal",
                    )
                ],
            ),
            GoalPackItem(
                title="Structural move",
                context="Perform the layout/module split with import fixes",
                desired=[
                    DraftDesired(
                        id="new-package-root",
                        kind="file_exists",
                        path="src",
                        why="New package root exists",
                    ),
                    DraftDesired(
                        id="pytest-collects",
                        kind="command",
                        run="python -m pytest --collect-only -q",
                        why="Collection survives the move",
                    ),
                ],
            ),
            GoalPackItem(
                title="Behaviour lock",
                context="Prove external behaviour still holds",
                desired=[
                    DraftDesired(
                        id="tests-pass",
                        kind="command",
                        run="python -m pytest -q",
                        why="Full suite green after refactor",
                        risk="Need real coverage; empty suite is vacuous",
                    )
                ],
            ),
        ]

    if not desired and not pack:
        # Generic safe starter for free-text chores
        add_file(
            "artifact-exists",
            "README.md",
            "Fallback: require a concrete artifact — replace with a real path",
            "Generic fallback; edit before submit",
        )
        if any(k in ctx for k in ("test", "pytest", "verify")):
            add_cmd(
                "verify-tests",
                "python -m pytest -q",
                "Verify with the project test suite",
                "May be vacuous without relevant tests",
            )

    warnings = stress_check(desired, constraints, context=context)
    return SuggestResult(
        source="heuristic",
        context=context,
        task_class=task_class or "repo-chore",
        desired=desired,
        constraints=constraints,
        warnings=warnings,
        pack=pack,
    )


def stress_check(
    desired: list[DraftDesired],
    constraints: list[DraftConstraint],
    *,
    context: str = "",
) -> list[StressWarning]:
    warnings: list[StressWarning] = []
    hard = [d for d in desired if d.weight >= 1.0 and d.kind != "judge"]
    if not hard and not constraints:
        warnings.append(
            StressWarning(
                code="no_hard_criteria",
                message="Draft has no required non-judge desired states",
                severity="block",
            )
        )

    for d in desired:
        if d.kind == "command":
            run = (d.run or "").strip()
            if run in {"true", ":", "exit 0"}:
                warnings.append(
                    StressWarning(
                        code="vacuous_command",
                        message=f"{d.id}: command {run!r} is vacuous",
                        severity="block",
                    )
                )
            if "pytest" in run and "testpaths" not in _norm(context):
                warnings.append(
                    StressWarning(
                        code="pytest_without_testpaths",
                        message=(
                            f"{d.id}: pytest may pass with an empty/irrelevant suite — "
                            "pair with pytest.ini testpaths or an explicit test path"
                        ),
                        severity="warn",
                    )
                )

    ctx = _norm(context)
    if any(k in ctx for k in ("don't touch", "do not touch", "must not modify", "leave src")):
        if not any(c.kind == "must_not_modify" for c in constraints):
            warnings.append(
                StressWarning(
                    code="missing_must_not_modify",
                    message="Context asks to preserve paths but no must_not_modify constraint was drafted",
                    severity="warn",
                )
            )

    if len(ctx) > 180 and any(k in ctx for k in ("refactor", "re-architect", "split", "migrate")):
        warnings.append(
            StressWarning(
                code="prefer_goal_pack",
                message="Large brief detected — prefer a Goal pack over one mega-Goal",
                severity="info",
            )
        )
    return warnings


def _parse_model_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    # Strip markdown fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # try first {...} blob
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _drafts_from_model_payload(
    data: dict[str, Any],
) -> tuple[list[DraftDesired], list[DraftConstraint], list[GoalPackItem]]:
    desired: list[DraftDesired] = []
    for raw in data.get("desired") or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "")
        if kind not in {"file_exists", "file_contains", "command"}:
            continue
        desired.append(
            DraftDesired(
                id=str(raw.get("id") or f"d{len(desired)+1}"),
                kind=kind,
                path=raw.get("path"),
                pattern=raw.get("pattern"),
                run=raw.get("run"),
                weight=float(raw.get("weight") or 1.0),
                why=str(raw.get("why") or ""),
                risk=str(raw.get("risk") or ""),
            )
        )
    constraints: list[DraftConstraint] = []
    for raw in data.get("constraints") or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "")
        if kind not in {"must_not_modify", "must_pass_command", "budget_ceiling", "no_external_effects"}:
            continue
        val: str | float | list[str]
        raw_val = raw.get("value")
        if raw_val is None:
            val = ""
        elif isinstance(raw_val, list):
            val = [str(x) for x in raw_val]
        elif isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool):
            val = float(raw_val)
        else:
            val = str(raw_val)
        kind_lit: Any = kind
        constraints.append(
            DraftConstraint(
                id=str(raw.get("id") or f"c{len(constraints)+1}"),
                kind=kind_lit,
                value=val,
                why=str(raw.get("why") or ""),
            )
        )
    pack: list[GoalPackItem] = []
    for raw in data.get("pack") or []:
        if not isinstance(raw, dict):
            continue
        d_list, c_list, _ = _drafts_from_model_payload(
            {"desired": raw.get("desired") or [], "constraints": raw.get("constraints") or []}
        )
        pack.append(
            GoalPackItem(
                title=str(raw.get("title") or "Goal"),
                context=str(raw.get("context") or ""),
                desired=d_list,
                constraints=c_list,
            )
        )
    return desired, constraints, pack


_SYSTEM = """You draft Recertia Goal criteria. Return ONLY JSON with keys:
desired (array), constraints (array), pack (array, optional for large work).
Each desired: id, kind (file_exists|file_contains|command), path?, pattern?, run?, why, risk, weight=1.0.
Each constraint: id, kind (must_not_modify|must_pass_command|...), value, why.
Never invent judge-only goals. Prefer small machine-checkable checks.
For large refactors, put a multi-goal pack and keep desired minimal.
Do not claim criteria are locked — drafts only."""


def model_suggest(
    *,
    context: str,
    task_class: str = "repo-chore",
    client: Any | None = None,
) -> SuggestResult | None:
    """Ask a model for drafts; return None if unavailable or unparseable."""

    if client is None:
        try:
            from recertia.solver.factory import build_model_client

            client = build_model_client(role="solver")
        except Exception:  # noqa: BLE001
            return None
        # Stub clients are useless for drafting
        if getattr(client, "provider", None) == "stub":
            return None

    prompt = (
        f"task_class={task_class}\n"
        f"context:\n{context}\n\n"
        "Draft desired states and constraints as JSON."
    )
    try:
        resp = client.complete(prompt, system=_SYSTEM)
        text = resp.text if hasattr(resp, "text") else str(resp)
    except Exception:  # noqa: BLE001
        return None

    data = _parse_model_json(text)
    if not data:
        return None
    desired, constraints, pack = _drafts_from_model_payload(data)
    if not desired and not pack:
        return None
    warnings = stress_check(desired, constraints, context=context)
    return SuggestResult(
        source="model",
        context=context,
        task_class=task_class or "repo-chore",
        desired=desired,
        constraints=constraints,
        warnings=warnings,
        pack=pack,
    )


def suggest_criteria(
    *,
    context: str,
    task_class: str = "repo-chore",
    use_model: bool = True,
) -> SuggestResult:
    """Compose entrypoint: model draft with heuristic fallback."""

    context = (context or "").strip()
    if not context:
        return SuggestResult(
            source="heuristic",
            context="",
            task_class=task_class or "repo-chore",
            desired=[],
            constraints=[],
            warnings=[
                StressWarning(
                    code="empty_context",
                    message="Provide context before suggesting criteria",
                    severity="block",
                )
            ],
        )

    if use_model:
        modeled = model_suggest(context=context, task_class=task_class)
        if modeled is not None:
            return modeled
    return heuristic_suggest(context=context, task_class=task_class)


def drafts_to_goal(
    result: SuggestResult,
    *,
    only_selected: bool = True,
    goal_id: str | None = None,
) -> Goal:
    """Build a Goal from accepted drafts (for server-side validation helpers)."""

    desired_src = [d for d in result.desired if d.selected] if only_selected else list(result.desired)
    if not desired_src and result.pack:
        # Use first pack item if top-level empty
        desired_src = list(result.pack[0].desired)
    desired = [DesiredState.model_validate(d.to_desired_dict()) for d in desired_src]
    from contracts.goal import Constraint

    cons_src = (
        [c for c in result.constraints if c.selected] if only_selected else list(result.constraints)
    )
    constraints = [Constraint.model_validate(c.to_constraint_dict()) for c in cons_src]
    return Goal(
        goal_id=goal_id or "compose-draft",
        desired=desired,
        constraints=constraints,
        context=result.context or None,
        task_class=result.task_class,
    )
