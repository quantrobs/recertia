# Contributing

Recertia is a single Python (>=3.11) package. Contracts in [`contracts/`](contracts)
are the structural source of truth (ADR-0009). Implementation lives in
[`src/recertia/`](src/recertia).

Contributions are accepted under the [PolyForm Noncommercial License 1.0.0](LICENSE).
This is **not** MIT. Do not send a change that assumes commercial-use rights.

## Setup

```bash
pip install -e ".[dev]"
export PATH="$HOME/.local/bin:$PATH"   # if `recertia` is not on PATH
```

Docker is required only for the container executor. Local development and the
pytest suite use the local backend:

```bash
recertia run --goal evals/golden/repo-chore/add-editorconfig/goal.json --local-exec
pytest -v
```

API `POST /v1/runs` refuses the local backend unless `RECERTIA_API_ALLOW_LOCAL_EXEC=1`
is set (break-glass). Pytest already sets that in `tests/conftest.py`.

## Checks before you send a change

These match [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

```bash
ruff check contracts/ src/ scripts/ tests/ conftest.py
mypy contracts/ src/recertia/
python3 scripts/generate_schemas.py --check
python3 scripts/export_examples.py --check
recertia skills lint --skills-root skills
python3 scripts/check_cross_refs.py --check
python3 scripts/check_milestone_deps.py --check
python3 scripts/check_assumptions_hygiene.py --check
python3 scripts/security_review.py --check
pytest -v
```

If you change a model in `contracts/`, regenerate schemas:

```bash
python3 scripts/generate_schemas.py
```

Do not hand-edit files under `schema/`.

## What belongs in a PR

- Keep diffs on-task. Do not rewrite archived Q3 plans or mark research assumptions
  in [`docs/assumptions.md`](docs/assumptions.md) `supported` from CI alone.
- Default T2 policy is [`policy/default.json`](policy/default.json). Weekly job spend
  belongs in `.recertia/job_quota.json`, not in that file.
- HEX/compress flags stay off unless the enablement predicates in
  [`docs/specifications/remaining-work.md`](docs/specifications/remaining-work.md) hold.

Cursor Cloud notes for this repo are in [`AGENTS.md`](AGENTS.md). Architecture and
specs are indexed from [`docs/architecture.md`](docs/architecture.md) and
[`docs/specifications.md`](docs/specifications.md).
