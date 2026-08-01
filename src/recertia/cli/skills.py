"""CLI: lint, search, and promote skills in the procedural library."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

skills_app = typer.Typer(help="Lint and search the skill library.")


def register_skills_commands(app: typer.Typer) -> None:
    app.add_typer(skills_app, name="skills")


@skills_app.command("lint")
def skills_lint(
    skills_root: Path = typer.Option(Path("skills"), "--skills-root"),
) -> None:
    """Structural + semantic lint of every skill version under ``skills_root``."""

    from recertia.memory.procedural.lint import lint_store
    from recertia.memory.procedural.store import SkillStore

    store = SkillStore(skills_root)
    report = lint_store(store)
    failures = {k: v for k, v in report.items() if v}
    for key, violations in report.items():
        if violations:
            typer.echo(f"FAIL {key}")
            for v in violations:
                typer.echo(f"  - {v}")
        else:
            typer.echo(f"OK   {key}")
    if failures:
        raise typer.Exit(code=1)


@skills_app.command("search")
def skills_search(
    query: str = typer.Argument(...),
    skills_root: Path = typer.Option(Path("skills"), "--skills-root"),
    index_path: Path = typer.Option(Path(".recertia/skill_index.db"), "--index"),
    workdir: Path = typer.Option(Path("."), "--workdir"),
    explain: bool = typer.Option(False, "--explain", help="Print scores and drop reasons."),
    env: Optional[str] = typer.Option(
        None, "--env", help="JSON object of tool→version for fingerprint matching."
    ),
) -> None:
    """Retrieval debug endpoint (specs §9): scores and drop reasons without running a task."""

    from recertia.memory.procedural.store import SkillStore
    from recertia.retrieval.index import SkillIndex
    from recertia.retrieval.pipeline import Retriever

    store = SkillStore(skills_root)
    index = SkillIndex(index_path)
    try:
        fingerprint = store.library_fingerprint()
        if not index.is_fresh(fingerprint):
            index.rebuild(store.iter_loaded(), library_fingerprint=fingerprint)
        retriever = Retriever(index)
        env_fp = json.loads(env) if env else {}
        bundle, explanation = retriever.search(
            query, workdir=workdir, env_fingerprint=env_fp
        )
    finally:
        index.close()

    if explain:
        typer.echo(f"snapshot={explanation.snapshot_id}")
        typer.echo(
            f"lexical_hits={len(explanation.lexical_hits)} "
            f"vector_hits={len(explanation.vector_hits)}"
        )
        for d in explanation.dropped:
            typer.echo(f"  DROP {d.skill_id}@v{d.version} stage={d.stage} reason={d.reason}")
        for sid, ver, score, reason in explanation.demoted:
            typer.echo(f"  DEMOTE {sid}@v{ver} score={score:.3f} ({reason})")
    for c in bundle.skills:
        typer.echo(f"{c.skill_id}@v{c.version} score={c.score}")
    if not bundle.skills:
        typer.echo("(empty bundle)")


@skills_app.command("promote")
def skills_promote(
    skill_id: str = typer.Argument(..., help="Skill id to promote."),
    version: int = typer.Option(..., "--version", help="Immutable version number."),
    skills_root: Path = typer.Option(Path("skills"), "--skills-root"),
    golden_dir: Optional[Path] = typer.Option(
        None, "--golden-dir", help="Single-fixture golden directory (M1 path)."
    ),
    golden_root: Optional[Path] = typer.Option(
        None, "--golden-root", help="Task-class golden root (M4 path)."
    ),
    runs_root: Path = typer.Option(Path(".recertia/promote-runs"), "--runs-root"),
    log_dir: Path = typer.Option(Path("evals/golden/_promotion_logs"), "--log-dir"),
    require_task_class_gate: bool = typer.Option(
        False, "--require-task-class-gate", help="Require full task-class harness."
    ),
    model_validated_on: str = typer.Option("m1-seed", "--model-validated-on"),
) -> None:
    """Promote a skill to approved after the golden regression gate (specs §8)."""

    from recertia.memory.procedural.promote import PromotionError, promote_to_approved
    from recertia.memory.procedural.store import SkillStore

    if golden_dir is None and golden_root is None:
        typer.echo("provide --golden-dir and/or --golden-root", err=True)
        raise typer.Exit(code=2)

    store = SkillStore(skills_root)
    repo_root = Path.cwd()
    try:
        status = promote_to_approved(
            store,
            skill_id,
            version,
            golden_dir=golden_dir,
            golden_root=golden_root,
            runs_root=runs_root,
            log_dir=log_dir,
            model_validated_on=model_validated_on,
            repo_root=repo_root,
            require_task_class_gate=require_task_class_gate,
        )
    except PromotionError as exc:
        typer.echo(f"PROMOTION FAILED: {exc}", err=True)
        if exc.failing_fixtures:
            typer.echo(f"failing_fixtures={','.join(exc.failing_fixtures)}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"skill_id={status.skill_id} version={status.version} "
        f"lifecycle={status.lifecycle} active={status.active}"
    )
    if status.certification.golden_set_ref:
        typer.echo(f"golden_set_ref={status.certification.golden_set_ref}")
