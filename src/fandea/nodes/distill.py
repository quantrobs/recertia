"""``distill``: success distillation, fact extraction, failure-cluster pitfalls (M3)."""

from __future__ import annotations

import json
from pathlib import Path

from contracts.run import ReusabilityVerdict, RunState
from contracts.skill import SkillVersion
from fandea.distill.failure_clusters import author_pitfall_skill, cluster_dead_ends
from fandea.distill.prior import load_authoring_prior
from fandea.distill.success import distill_success
from fandea.memory.episodic import CaseRecord
from fandea.nodes.context import NodeContext, NodeOutcome


def distill(state: RunState, ctx: NodeContext) -> NodeOutcome:
    # Eval firewall (specs §19): fixture runs must not write episodic / draft / facts / store.
    if state.task.is_eval_fixture:
        verdict = ReusabilityVerdict(
            verdict="one_off",
            parameterisable=False,
            context_free=True,
            checkable=True,
            not_duplicate=True,
            bounded=True,
            reason="eval firewall: fixture run — distillation and memory writes suppressed",
        )
        return NodeOutcome(
            state=state.model_copy(update={"reusability": verdict, "draft": None, "facts_extracted": []}),
            route="one_off",
            note=verdict.reason,
        )

    # Control arm: measure without learning — before any episodic/fact/draft writes.
    if state.arm == "control":
        verdict = ReusabilityVerdict(
            verdict="one_off",
            parameterisable=False,
            context_free=True,
            checkable=True,
            not_duplicate=True,
            bounded=True,
            reason="control arm — distillation suppressed",
        )
        return NodeOutcome(
            state=state.model_copy(update={"reusability": verdict}),
            route="one_off",
            note=verdict.reason,
        )

    # Always record the solved attempt episodically (M2 behaviour retained) for non-fixture runs.
    if ctx.episodic is not None:
        approach = (
            f"skill:{state.chosen.skill_id}@v{state.chosen.version}"
            if state.chosen
            else f"strategy:{state.strategy or 'scratch'}"
        )
        case = CaseRecord(
            case_id=f"{ctx.run_id}-a{state.attempt_no}",
            run_id=ctx.run_id,
            attempt_no=state.attempt_no,
            task_class=state.task.task_class,
            request_excerpt=state.task.request[:200],
            outcome="solved",
            transcript_ref=state.transcript_ref,
            approach=approach,
            skill_id=state.chosen.skill_id if state.chosen else None,
            skill_version=state.chosen.version if state.chosen else None,
        )
        ctx.episodic.write(case)

    # Applying an existing skill is evidence, not a new library entry (unless scratch).
    if state.strategy in ("apply", "adapt") and state.chosen is not None:
        verdict = ReusabilityVerdict(
            verdict="one_off",
            parameterisable=True,
            context_free=True,
            checkable=True,
            not_duplicate=True,
            bounded=True,
            reason=(
                f"solved via existing skill {state.chosen.skill_id}@v{state.chosen.version}; "
                "recorded as evidence, not a new draft"
            ),
        )
        _record_one_off(ctx, state, verdict)
        new_state = state.model_copy(update={"reusability": verdict, "facts_extracted": []})
        return NodeOutcome(state=new_state, route="one_off", note=verdict.reason)

    prior = load_authoring_prior()
    commands = _commands_from_context(state, ctx)
    sightings = _task_class_sightings(ctx, state.task.task_class)
    near = _nearest_duplicate(ctx, state.task.request)

    draft, facts, verdict = distill_success(
        state,
        workdir=ctx.workdir,
        commands=commands,
        prior=prior,
        task_class_sightings=sightings,
        near_duplicate_of=near,
    )

    # Without a skill store the graph cannot persist memory — keep M0/M1 one_off behaviour.
    if ctx.store is None and verdict.verdict == "reusable":
        verdict = ReusabilityVerdict(
            verdict="one_off",
            parameterisable=verdict.parameterisable,
            context_free=verdict.context_free,
            checkable=verdict.checkable,
            not_duplicate=verdict.not_duplicate,
            bounded=verdict.bounded,
            reason="skill store not configured; recording as one_off evidence",
        )
        draft = None

    # Failure-cluster side path: author pitfall skills when threshold met (does not block success path).
    pitfall_note = None
    if ctx.episodic is not None and state.task.task_class:
        clusters = cluster_dead_ends(ctx.episodic, task_class=state.task.task_class, min_runs=3)
        if clusters and ctx.store is not None:
            # Pitfalls are enqueued as drafts onto state when produced; store path handles approved ones.
            sig, cluster = clusters[0]
            neg = ctx.workdir / ".fandea-pitfall-neg"
            neg.mkdir(exist_ok=True)
            pitfall = author_pitfall_skill(
                task_class=state.task.task_class,
                signature=sig,
                cluster=cluster,
                negative_workdir=neg,
            )
            pitfall_note = f"failure-cluster ready: {pitfall.skill_id}"
            if draft is None:
                # Prefer surfacing the pitfall as the draft when success path is one_off.
                draft = pitfall
                from contracts.run import ReusabilityVerdict as RV

                if pitfall.certification_criteria[0].is_preregistered_and_proven:
                    verdict = RV(
                        verdict="reusable",
                        parameterisable=True,
                        context_free=True,
                        checkable=True,
                        not_duplicate=True,
                        bounded=True,
                        reason="failure-cluster pitfall skill",
                    )

    _record_one_off(ctx, state, verdict)

    facts_payload = [f.model_dump(mode="json") for f in facts]
    draft_payload = draft.model_dump(mode="json") if isinstance(draft, SkillVersion) else None
    new_state = state.model_copy(
        update={
            "draft": draft_payload,
            "facts_extracted": facts_payload,
            "reusability": verdict,
        }
    )
    route = "reusable" if verdict.verdict == "reusable" and draft_payload else "one_off"
    if route == "one_off" and verdict.verdict == "reusable":
        # Draft missing despite reusable claim — degrade safely.
        verdict = verdict.model_copy(update={"verdict": "one_off", "reason": "draft missing"})
        new_state = new_state.model_copy(update={"reusability": verdict})
    note = verdict.reason
    if pitfall_note:
        note = f"{note}; {pitfall_note}"
    if draft is not None and draft.provenance.authoring_prior_version:
        note = f"{note}; authoring_prior={draft.provenance.authoring_prior_version}"
    return NodeOutcome(state=new_state, route=route, note=note)


def _commands_from_context(state: RunState, ctx: NodeContext) -> list[str]:
    if ctx.script:
        return list(ctx.script)
    if state.transcript_ref and ctx.transcripts is not None:
        try:
            payload = ctx.transcripts.read(state.transcript_ref)
        except Exception:  # noqa: BLE001
            payload = {}
        cmds: list[str] = []
        for event in payload.get("events", []):
            if event.get("kind") == "tool":
                tool = (event.get("payload") or {}).get("tool")
                inputs = (event.get("payload") or {}).get("inputs") or {}
                if tool == "shell" and inputs.get("command"):
                    cmds.append(str(inputs["command"]))
            # Applicator may record shell under step_end payloads.
            if event.get("kind") == "step_end":
                cmd = (event.get("payload") or {}).get("command")
                if cmd:
                    cmds.append(str(cmd))
        if cmds:
            return cmds
    return []


def _task_class_sightings(ctx: NodeContext, task_class: str | None) -> int:
    if not task_class or ctx.episodic is None:
        return 1
    return sum(1 for row in ctx.episodic.list_index() if row.get("task_class") == task_class)


def _nearest_duplicate(ctx: NodeContext, request: str) -> tuple[str, int] | None:
    if ctx.store is None:
        return None
    # Simple lexical near-duplicate: identical skill_id slug prefix.
    from fandea.distill.success import _skill_id_from_request

    want = _skill_id_from_request(request)
    for version, status, _stats in ctx.store.iter_loaded():
        if status.lifecycle in ("approved", "candidate", "shadow") and version.skill_id == want:
            return (version.skill_id, version.version)
    return None


def _record_one_off(ctx: NodeContext, state: RunState, verdict: ReusabilityVerdict) -> None:
    if verdict.verdict != "one_off" or ctx.one_off_log is None:
        return
    path = Path(ctx.one_off_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "run_id": state.run_id,
                    "task_class": state.task.task_class,
                    "reason": verdict.reason,
                }
            )
            + "\n"
        )
