# AGENTS.md

## Cursor Cloud specific instructions

Fandea is a single Python (>=3.11) package. The runtime is a cyclic graph orchestrator exposed
through two surfaces: the `fandea` CLI and a FastAPI HTTP API. Persistence is embedded SQLite +
files under a gitignored `.fandea/` dir; no external database is required for development.

### Environment / dependencies

- The startup update script runs `pip install -e ".[dev]"` (editable install with test + lint +
  API extras). Standard commands live in `pyproject.toml` and `.github/workflows/ci.yml`.
- Console scripts (`fandea`, `pytest`, `ruff`, `mypy`, `uvicorn`) install to `~/.local/bin`.
  That dir is added to `PATH` via `~/.bashrc`; if a fresh non-login shell can't find `fandea`,
  run `export PATH="$HOME/.local/bin:$PATH"`.

### Execution backend (important gotcha)

- Production default is `FANDEA_EXECUTION_BACKEND=container` (Docker/Podman). **Docker is NOT
  installed in this environment**, so the container backend and the `container-smoke` CI job
  cannot run here.
- For development, always use the local executor instead:
  - CLI: add `--local-exec` to `fandea run` / `fandea resume`.
  - API: start uvicorn with `FANDEA_EXECUTION_BACKEND=local` in the environment, otherwise
    `POST /v1/runs` returns `503` (SandboxError).
- The pytest suite already forces the local backend via `tests/conftest.py`, so `pytest` needs
  no Docker.

### Lint / test / build

- Lint + types: `ruff check contracts/ src/ scripts/ tests/ conftest.py` and
  `mypy contracts/ src/fandea/`.
- Drift/hygiene checks (part of CI): the `--check` scripts under `scripts/`
  (`generate_schemas.py`, `export_examples.py`, `check_cross_refs.py`, `check_milestone_deps.py`,
  `check_assumptions_hygiene.py`). `schema/` is generated from `contracts/` — regenerate with
  `python3 scripts/generate_schemas.py` when contracts change, or CI's drift check fails.
- Tests: `pytest -v` (fast, ~10s).

### Running the surfaces

- CLI run (example): `fandea run --goal evals/golden/repo-chore/add-editorconfig/goal.json
  --local-exec --runs-root .fandea --workdir .fandea/ws`. Inspect with
  `fandea runs show <run_id> --route-log` and `fandea ledger verify`.
- HTTP API: `FANDEA_EXECUTION_BACKEND=local uvicorn fandea.api.app:app --host 127.0.0.1 --port 8000`
  (default port 8000; interactive docs at `/docs`). Endpoints under `/v1/*` require an
  `X-API-Key` header. Issue a key that writes to the same root the server uses
  (`.fandea/api_keys.sqlite`): `fandea keys issue --tenant demo --scopes runs,metrics --actor dev`.
