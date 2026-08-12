"""``distill``: success distillation and fact extraction (M3).

Failure-cluster authoring is a scheduled job / Practice curriculum (ADR-0015).
This node MUST NOT scan the episodic store for clusters.
"""

from __future__ import annotations

import json
from pathlib import Path

from contracts.run import ReusabilityVerdict, RunState
from contracts.skill import SkillVersion
from recertia.distill.prior import load_authoring_prior
from recertia.distill.success import distill_success
from recertia.memory.episodic import CaseRecord
from recertia.nodes.context import NodeContext, NodeOutcome


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

    # Non-treatment arms: measure without learning — before any episodic/fact/draft writes.
    if state.arm in ("control", "shadow"):
        verdict = ReusabilityVerdict(
            verdict="one_off",
            parameterisable=False,
            context_free=True,
            checkable=True,
            not_duplicate=True,
            bounded=True,
            reason=f"{state.arm} arm — distillation suppressed",
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
            request_excerpt=(state.task.request or "")[:200],
            outcome="solved",
            transcript_ref=state.transcript_ref,
            approach=approach,
            skill_id=state.chosen.skill_id if state.chosen else None,
            skill_version=state.chosen.version if state.chosen else None,
            session_id=state.task.submitted_by or ctx.run_id,
        )
        ctx.episodic.write(case)

    # Applying an existing skill is evidence, not a new library entry (unless scratch).
    if state.strategy in ("apply", "adapt") and state.chosen is not None:
        _note_apply_session(ctx, state)
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
    near = _nearest_duplicate(ctx, state.task.request or "")

    draft, facts, verdict = distill_success(
        state,
        workdir=ctx.workdir,
        commands=commands,
        prior=prior,
        task_class_sightings=sightings,
        near_duplicate_of=near,
    )

    if draft is not None and state.execution_guide is not None:
        from recertia.nodes.guide_stitch import reject_guide_leak

        leak = reject_guide_leak(draft.model_dump_json(), state.execution_guide)
        if leak:
            verdict = ReusabilityVerdict(
                verdict="one_off",
                parameterisable=False,
                context_free=True,
                checkable=True,
                not_duplicate=True,
                bounded=True,
                reason=leak,
            )
            draft = None

    # Without a skill store the graph cannot persist memory — keep M0/M1 one_off behaviour.
    # Without a reviewer, do not enter review (which would mark a *solved* task as
    # terminal=rejected); retain the draft on state for later promotion.
    if verdict.verdict == "reusable" and (ctx.store is None or ctx.reviewer is None):
        if ctx.store is None:
            reason = "skill store not configured; recording as one_off evidence"
            draft = None
        else:
            reason = "reviewer not configured; draft retained without promotion"
        verdict = ReusabilityVerdict(
            verdict="one_off",
            parameterisable=verdict.parameterisable,
            context_free=verdict.context_free,
            checkable=verdict.checkable,
            not_duplicate=verdict.not_duplicate,
            bounded=verdict.bounded,
            reason=reason,
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
    if draft is not None and draft.provenance.authoring_prior_version:
        note = f"{note}; authoring_prior={draft.provenance.authoring_prior_version}"
    return NodeOutcome(state=new_state, route=route, note=note)


def _note_apply_session(ctx: NodeContext, state: RunState) -> None:
    store = ctx.store
    chosen = state.chosen
    if store is None or chosen is None:
        return
    if not hasattr(store, "get_stats") or not hasattr(store, "write_stats"):
        return
    from recertia.memory.procedural.apply_diversity import note_apply_session

    session_id = state.task.submitted_by or ctx.run_id
    try:
        note_apply_session(
            store,  # type: ignore[arg-type]
            skill_id=chosen.skill_id,
            version=chosen.version,
            session_id=session_id,
        )
    except FileNotFoundError:
        return


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
    return ctx.episodic.count_for_task_class(task_class)


def _nearest_duplicate(ctx: NodeContext, request: str) -> tuple[str, int] | None:
    if ctx.store is None:
        return None
    # Simple lexical near-duplicate: identical skill_id slug prefix.
    from recertia.distill.success import _skill_id_from_request

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
