# Single-user go-live

How to run Recertia as a local agent with a real model, allowlisted network tools,
and a lint-clean seed library.

## Credentials

| Provider | Env vars |
| --- | --- |
| Anthropic | `ANTHROPIC_API_KEY`, `RECERTIA_MODEL_PROVIDER=anthropic`, `RECERTIA_MODEL_ID=claude-…` |
| OpenAI | `OPENAI_API_KEY`, `RECERTIA_MODEL_PROVIDER=openai`, `RECERTIA_MODEL_ID=gpt-…` |
| Override key env | `RECERTIA_API_KEY_ENV=MY_KEY_VAR` |
| Optional verifier | `RECERTIA_VERIFIER_MODEL_ID=…` (same provider family) |

CLI shorthand:

```bash
recertia run --goal goal.json --model anthropic:claude-sonnet-4-20250514 --local-exec
recertia run --spec task.json --model openai:gpt-4.1
```

Stub (default) leaves the solver model unset so scratch fails loudly instead of
running a silent `true`. For offline demos only:

```bash
RECERTIA_ALLOW_STUB_MODEL=1 recertia run --spec task.json --model stub
```

## Tools required by seed skills

| Tool | Role |
| --- | --- |
| `shell` / `edit_file` / `read_file` / `grep` | Repo chore primitives |
| `fetch` | Allowlisted HTTP GET (default hosts: `pypi.org`, `files.pythonhosted.org`, `raw.githubusercontent.com`, `api.github.com`) |
| `agent_subtask` | Model-backed one-command repair loop (needs a configured model) |

Tune fetch with `RECERTIA_FETCH_ALLOWLIST`, `RECERTIA_FETCH_TIMEOUT_S`, `RECERTIA_FETCH_MAX_BYTES`.

## Seed library

```bash
python3 scripts/install_seed_library.py --rewrite-versions
recertia skills lint
```

Approved seeds must carry hash-bound sensitivity proofs (`evidence_hash`). CI runs
`recertia skills lint` on every change that touches `skills/`.

## Jobs and retention

```bash
recertia jobs run curator --dry-run
recertia jobs run practice --one-off "lockfile drift"
recertia jobs run mine --hint "docs/runbook.md" --submit
recertia gc --older-than-days 14 --dry-run
recertia gc --older-than-days 14
```

Jobs emit proposals / candidates only — never write `approved` (M7).

## Execution backend

Prefer containers for anything beyond local demos:

```bash
export RECERTIA_EXECUTION_BACKEND=container
# or: recertia run … --local-exec   # sets backend=local for this process
```

See [container-sandbox.md](container-sandbox.md).
