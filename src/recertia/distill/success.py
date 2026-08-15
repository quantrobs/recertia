"""Success-path distillation: transcript → SkillVersion draft + facts (specs §7, §25)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from contracts.criteria import SkillCertificationCriterion
from contracts.fact import Fact, FactProvenance
from contracts.policy import AuthoringPrior
from contracts.run import ReusabilityVerdict, RunState
from contracts.skill import (
    FailureMode,
    Hygiene,
    Parameter,
    Provenance,
    SkillVersion,
    Step,
)
from recertia.distill.prior import load_authoring_prior
from recertia.distill.reusability import assess_reusability
from recertia.validation.sensitivity import author_sensitivity_proof, empty_negative_fixture

_SHELL_TOKEN = re.compile(r"[A-Za-z0-9_./\-]+\.(?:txt|md|py|toml|yml|yaml|json|gitignore)")


def distill_success(
    state: RunState,
    *,
    workdir: Path,
    commands: list[str],
    prior: AuthoringPrior | None = None,
    task_class_sightings: int = 1,
    near_duplicate_of: tuple[str, int] | None = None,
    one_off_counts: dict[str, int] | None = None,
) -> tuple[SkillVersion | None, list[Fact], ReusabilityVerdict]:
    """Author a draft skill from a solved scratch/apply attempt.

    Returns ``(draft_or_none, facts, reusability_verdict)``.
    """

    from contracts.run import ReusabilityVerdict as _RV  # local alias unused; type in signature

    del _RV
    prior = prior or load_authoring_prior()
    task_class = state.task.task_class or "repo-chore"
    request = state.task.request or ""
    commands = [c for c in commands if c.strip() and not c.strip().startswith("true  #")]
    if not commands:
        commands = _infer_commands_from_workdir(workdir, request)

    params, parametrized = _extract_parameters(request, commands)
    skill_id = _skill_id_from_request(request)
    steps = [
        Step(
            id=f"step_{i}",
            tool="shell",
            intent=f"Execute distilled shell step {i} for {skill_id}",
            inputs={"command": cmd},
            resources=[],
        )
        for i, cmd in enumerate(parametrized, start=1)
    ][: prior.max_steps]
    if not steps:
        steps = [
            Step(
                id="step_1",
                tool="shell",
                intent=f"No-op placeholder for {skill_id} pending richer transcript",
                inputs={"command": "true"},
            )
        ]

    check_cmd = _default_check_command(workdir, request)
    cert = SkillCertificationCriterion(
        id="artifact-present",
        kind="command",
        run=check_cmd,
        authored_by="distiller",
        weight=1.0,
        preregistered=True,
    )
    neg = empty_negative_fixture()
    proof = author_sensitivity_proof(cert, negative_workdir=neg)
    cert = cert.model_copy(update={"sensitivity_proof": proof})

    now = datetime.now(timezone.utc)
    version = SkillVersion(
        skill_id=skill_id,
        version=1 if near_duplicate_of is None else near_duplicate_of[1] + 1,
        supersedes=near_duplicate_of[1] if near_duplicate_of else None,
        title=_title(request),
        intent=_intent(request),
        task_class=task_class,
        tags=[task_class, "distilled"],
        parameters=params,
        preconditions=[],
        steps=steps,
        certification_criteria=[cert],
        failure_modes=[
            FailureMode(
                symptom="certification criterion fails",
                response="restore snapshot and re-check parameters",
            )
        ],
        provenance=Provenance(
            distilled_from_run=state.run_id,
            distilled_at=now,
            curation="self_distilled",
            derivation="success_transcript",
            authoring_prior_version=prior.version,
            model=state.manifest.model,
        ),
        hygiene=Hygiene(secret_scan="skipped", scanned_at=None),
    )

    verdict = assess_reusability(
        version,
        task_class_sightings=task_class_sightings,
        near_duplicate_of=None if near_duplicate_of is None else near_duplicate_of,
    )
    # Near-duplicates are rewritten as next versions and still go through review.
    if verdict.verdict == "duplicate" and near_duplicate_of is not None:
        verdict = verdict.model_copy(
            update={
                "verdict": "reusable",
                "not_duplicate": True,
                "reason": (
                    f"new version of near-duplicate "
                    f"{near_duplicate_of[0]}@v{near_duplicate_of[1]}"
                ),
            }
        )

    facts = _extract_facts(state, workdir, skill_id)
    if verdict.verdict != "reusable":
        return None, facts, verdict
    return version, facts, verdict


def _extract_parameters(
    request: str, commands: list[str]
) -> tuple[list[Parameter], list[str]]:
    tokens = sorted(set(_SHELL_TOKEN.findall(request + " " + " ".join(commands))))
    params: list[Parameter] = []
    parametrized = list(commands)
    for i, token in enumerate(tokens[:3]):
        name = f"path_{i}" if "." in token else f"token_{i}"
        name = re.sub(r"[^a-z0-9_]", "_", name.lower())
        params.append(
            Parameter(
                name=name,
                type="path" if "/" in token or "." in token else "string",
                required=False,
                default=token,
            )
        )
        parametrized = [c.replace(token, "{{" + name + "}}") for c in parametrized]
    if not params:
        params = [Parameter(name="target", type="string", required=False, default=".")]
    return params, parametrized


def _infer_commands_from_workdir(workdir: Path, request: str) -> list[str]:
    files = [p for p in workdir.rglob("*") if p.is_file()]
    if not files:
        return []
    # Prefer writing the newest small text file as a reconstructible echo.
    newest = max(files, key=lambda p: p.stat().st_mtime)
    rel = newest.relative_to(workdir).as_posix()
    content = newest.read_text(encoding="utf-8", errors="replace")
    if len(content) < 500 and "\0" not in content:
        escaped = json.dumps(content)
        return [f"printf %s {escaped} > {rel}"]
    return [f"test -f {rel}"]


def _default_check_command(workdir: Path, request: str) -> str:
    files = [p.relative_to(workdir).as_posix() for p in workdir.rglob("*") if p.is_file()]
    if files:
        return f"test -f {files[0]}"
    tokens = _SHELL_TOKEN.findall(request)
    if tokens:
        return f"test -f {tokens[0]}"
    return "true"


def _skill_id_from_request(request: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", request.lower()).strip("-")
    slug = "-".join(p for p in slug.split("-") if p)[:48].strip("-")
    if len(slug) < 3:
        digest = hashlib.sha256(request.encode()).hexdigest()[:8]
        slug = f"distilled-{digest}"
    return slug


def _title(request: str) -> str:
    text = request.strip()
    if len(text) < 8:
        text = f"Distilled: {text}"
    return text[:120]


def _intent(request: str) -> str:
    text = request.strip()
    if len(text) < 20:
        text = f"Distilled skill covering request: {text}"
    return text[:500]


def _extract_facts(state: RunState, workdir: Path, skill_id: str) -> list[Fact]:
    now = datetime.now(timezone.utc)
    facts: list[Fact] = []
    for path in sorted(p for p in workdir.rglob("*") if p.is_file())[:3]:
        rel = path.relative_to(workdir).as_posix()
        slug = re.sub(r"[^a-z0-9]+", "-", rel.lower()).strip("-") or "file"
        facts.append(
            Fact(
                fact_id=f"{skill_id}-{slug}"[:64].strip("-"),
                slug=slug[:64].strip("-") or "file",
                assertion=(
                    f"Successful solve for {(state.task.request or '')!r} produced file {rel}"
                ),
                status="asserted",
                confidence=0.55,
                provenance=FactProvenance(
                    asserting_run=state.run_id,
                    evidence=f"workdir:{rel}",
                ),
                authored_at=now,
            )
        )
    return facts
