"""``store``: transactional skill + facts write, index update, ledger append (M3)."""

from __future__ import annotations

from contracts.fact import Fact
from contracts.run import RunState
from contracts.skill import SkillVersion
from contracts.stats import SkillStats
from contracts.status import SkillStatus
from fandea.memory.procedural.hygiene import require_clean
from fandea.nodes._util import now
from fandea.nodes.context import NodeContext, NodeOutcome


def store(state: RunState, ctx: NodeContext) -> NodeOutcome:
    if not state.draft:
        raise ValueError("store called without a draft")

    def _write() -> dict:
        version = SkillVersion.model_validate(state.draft)
        version = require_clean(version)
        if ctx.store is None:
            raise ValueError("store node requires SkillStore on NodeContext")

        ctx.store.write_version(version)
        # Task-plane code is allowed to persist a reviewable candidate only.
        # `promote_to_approved` is the sole state transition to approved and
        # runs the golden regression gate before writing that lifecycle.
        status = SkillStatus(
            skill_id=version.skill_id,
            version=version.version,
            lifecycle="candidate",
            active=False,
        )
        ctx.store.write_status(status)
        ctx.store.write_stats(SkillStats(skill_id=version.skill_id, version=version.version))

        written_facts: list[str] = []
        if ctx.facts is not None:
            for raw in state.facts_extracted:
                fact = Fact.model_validate(raw)
                stored = ctx.facts.write(fact)
                written_facts.append(stored.fact_id)

        if ctx.retriever is not None and hasattr(ctx.retriever, "index"):
            ctx.retriever.index.rebuild(ctx.store.iter_loaded())

        entry = ctx.ledger.append(
            actor=ctx.run_id,
            action="write",
            target=f"{version.skill_id}@v{version.version}",
            evidence={
                "run_id": ctx.run_id,
                "reusability": "reusable",
                "curation": version.provenance.curation,
                "authoring_prior_version": version.provenance.authoring_prior_version,
                "facts": written_facts,
            },
            at=now(),
        )
        return {
            "skill_id": version.skill_id,
            "version": version.version,
            "ledger_entry_seq": entry.seq,
            "facts": written_facts,
        }

    summary = ctx.op_once(0, _write)
    new_state = state.model_copy(
        update={
            "written_versions": [
                *state.written_versions,
                {
                    "skill_id": summary["skill_id"],
                    "version": summary["version"],
                    "ledger_entry_seq": summary["ledger_entry_seq"],
                    "facts": summary["facts"],
                },
            ]
        }
    )
    return NodeOutcome(
        state=new_state,
        route="always",
        note=f"wrote {summary['skill_id']}@v{summary['version']} ledger={summary['ledger_entry_seq']}",
    )
