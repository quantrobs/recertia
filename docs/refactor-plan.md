# Repository refactor plan

The design has landed. The repository has not. This plan turns a docs-and-spreadsheets
tree that grew by stacked PRs into a layout that can host M0 without another round of
structural debt.

Nothing here changes the architecture, specifications, or ADRs. It reorganises how those
artifacts, and the research that grounded them, sit in the tree — and lays down the
scaffolding the implementation plan already assumed.

## What is wrong today

| Symptom | Evidence | Cost if left alone |
| --- | --- | --- |
| Normative design and research dumps share one folder | `docs/` holds architecture, ADRs, *and* ~600 KB of `.xls`/`.xlsx` plus extracted bibliographies | Readers cannot tell what is load-bearing from what is a survey artifact; binary diffs poison every PR that touches scores |
| Duplicate spreadsheet formats | Every export ships both `.xls` and `.xlsx` | Two sources of truth; the `.xls` rewrite already drifted once during Blind Curator citation |
| No runtime skeleton | Root is `README`, `LICENSE`, `docs/`, `schema/` — no `src/`, no `pyproject.toml`, no CI | M0 starts by inventing layout the implementation plan already specified, and will invent it differently |
| Contracts live in three places | Prose in `specifications.md`, examples in fenced JSON, machine schemas in `schema/` | Drift is already the failure mode we keep fixing by hand |
| Docs are long single files | `architecture.md` ~840 lines, `specifications.md` ~950 | Diffs are noisy; section numbers are the only navigation; cross-doc `§` references are brittle |
| Stale remote branches | Stacked PR bases and `-f2c9` / `-1376` agent branches still on the remote after merge | The last merge cycle lost work on `main` precisely because a squash landed on a base that never reached `main` |
| Research findings arrive as binaries | Score rationales live inside Excel | The design change log in `references.md` cannot be regenerated from the survey without opening a workbook |

## Target layout

```text
fandea/
├── README.md
├── LICENSE
├── pyproject.toml                 # uv-managed; empty src until M0
├── .gitignore
├── .github/workflows/ci.yml       # schema, links, lint — before any runtime code
├── schema/                        # unchanged: skill.schema.json, run.schema.json
├── docs/
│   ├── architecture.md
│   ├── specifications.md
│   ├── implementation-plan.md
│   ├── refactor-plan.md           # this file
│   ├── references.md              # normative: findings that changed the design
│   └── adr/                       # unchanged
├── research/                      # everything that is evidence, not contract
│   ├── README.md
│   ├── preprints/
│   │   ├── scored.xlsx            # canonical; .xls dropped
│   │   └── scored.json            # regenerated from xlsx — diffable
│   └── score10-references/        # moved from docs/score10-references/
│       ├── README.md
│       ├── *.md
│       └── score10-references.json
├── src/fandea/                    # scaffolded empty packages matching M0 layout
├── tests/{unit,property,contract,boundary}/
├── evals/golden/                  # empty placeholder for M0 fixture
└── skills/                        # empty; first hand-authored skills arrive in M1
```

Rules the layout enforces:

1. **`docs/` is normative.** If it is in `docs/`, a change to it is a design change and needs
   an ADR or a specs edit. Spreadsheets never live here again.
2. **`research/` is evidence.** It may grow without touching contracts. Findings that change the
   design are *copied into* `references.md` with a stated change; the spreadsheet is not the
   design.
3. **`schema/` is the machine contract.** Specs may paraphrase; schemas win on conflict, and CI
   proves the fenced examples still validate.
4. **One spreadsheet format.** `.xlsx` is canonical. `.xls` is deleted. Anything that needs a
   legacy export regenerates it in a script, never stores it.

## Workstreams

### R0 — Separate research from design

Move, do not rewrite:

| From | To |
| --- | --- |
| `docs/preprints-self-improving-agents.xlsx` | `research/preprints/scored.xlsx` |
| `docs/preprints-score10-reference-lists.xlsx` | `research/preprints/score10-reference-lists.xlsx` |
| `docs/score10-references/` | `research/score10-references/` |
| `docs/preprints-*.xls` | **delete** |

Update links in `README.md` and `references.md`. Add `research/README.md` stating the evidence-
vs-contract rule and pointing at `docs/references.md` for absorbed findings.

**Done when:** `docs/` contains only markdown and ADRs; `rg --files docs -g '*.xls*' ` is empty;
every previous link resolves under `research/`.

### R1 — Make the survey diffable

Export `research/preprints/scored.json` from the workbook (one object per preprint: arXiv id,
score, band, rationale, `in_references`). Commit the JSON beside the xlsx. Add a tiny script
`scripts/export_scored_survey.py` and a CI check that the JSON matches the xlsx, so the next
scoring pass cannot land a binary-only change.

**Done when:** a one-line rationale edit shows up in `git diff` as text; CI fails if xlsx and
JSON disagree.

### R2 — Project skeleton matching the implementation plan

Land the empty tree from [`implementation-plan.md`](implementation-plan.md) "Repository layout",
minus the packages that have no code yet:

- `pyproject.toml` with Python 3.12, `ruff`, `mypy`, `pytest`, `jsonschema`, `pydantic` v2
- `src/fandea/{graph,nodes,memory,retrieval,solver,validation,distill,review,workspace,jobs,evals,ledger,governance,store,api,cli}/__init__.py`
- `tests/{unit,property,contract,boundary}/`
- `.gitignore` covering `.venv/`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/`, `*.egg-info/`
- `README.md` Status section updated: "Design complete; scaffolding in place; M0 is the first
  executable slice"

No runtime behaviour. The point is that M0 starts by filling packages, not by arguing about
where they go.

**Done when:** `uv sync` works; `pytest` collects zero tests and exits 0; `ruff` and `mypy`
run clean on empty packages.

### R3 — Contract CI before runtime CI

A workflow that runs on every PR and does not need the app:

| Check | What it proves |
| --- | --- |
| Schema validity | Both JSON Schemas pass `Draft202012Validator.check_schema` |
| Spec examples validate | Every fenced `json` block in `specifications.md` that looks like a skill or run validates against the matching schema |
| Cross-references resolve | Every `§n` / `§n.m` in `docs/*.md` points at a real heading in the same file or an explicitly prefixed cross-doc target |
| Relative links resolve | Every markdown link to a path in the repo hits a real file |
| Research export parity | `scored.json` matches `scored.xlsx` (after R1) |
| Import boundary stub | A test asserting `src/fandea/nodes` and `src/fandea/jobs` do not import `governance` or `evals.ablation` — green on empty packages, ready for M0 |

**Done when:** a deliberately broken `§99` reference and a schema-invalid skill example each fail
CI on a throwaway branch.

### R4 — Split the two load-bearing docs at their natural joints

Do not rewrite content. Cut along headings that already exist, with a thin index at the top of
each original path so existing links keep working:

`architecture.md` →

| File | Sections |
| --- | --- |
| `docs/architecture/README.md` | purpose, goals, three planes overview |
| `docs/architecture/memory.md` | §4 |
| `docs/architecture/task-plane.md` | §5 |
| `docs/architecture/skill-algebra.md` | §6 |
| `docs/architecture/promotion.md` | §7 |
| `docs/architecture/improvement-plane.md` | §8 |
| `docs/architecture/integrity.md` | §10–§14 |
| `docs/architecture/safety-and-metrics.md` | §15–§18 |

`specifications.md` →

| File | Sections |
| --- | --- |
| `docs/specifications/README.md` | entities overview + index |
| `docs/specifications/skill.md` | §1–§2 |
| `docs/specifications/run-and-nodes.md` | §3–§4 |
| `docs/specifications/retrieval-validation.md` | §5–§7 |
| `docs/specifications/memory-planes.md` | §13 |
| `docs/specifications/integrity.md` | §15–§19, §21–§22 |
| `docs/specifications/capacity.md` | §24–§25 |
| `docs/specifications/concurrency.md` | §26 |
| `docs/specifications/api-and-metrics.md` | §11–§12, §23 |

Keep `implementation-plan.md` and `references.md` whole — they are already single-purpose.
Redirect stubs at the old paths for one milestone, then delete.

**Done when:** no file under `docs/architecture/` or `docs/specifications/` exceeds ~250 lines;
the cross-reference CI from R3 still passes; `README.md` document table points at the indexes.

### R5 — Branch and PR hygiene

One-time cleanup, then a rule:

1. Delete merged remote branches:
   `cursor/self-improving-architecture-1376`,
   `cursor/library-capacity-and-references-1376`,
   `cursor/graph-execution-and-verifier-isolation-1376`,
   `cursor/preprints-xls-export-f2c9`,
   `cursor/preprints-applicability-scores-f2c9`,
   `cursor/score10-reference-lists-f2c9`.
2. **No stacked PRs against non-`main` bases** unless the base PR is already merged to `main`.
   The last cycle lost the graph-execution work on `main` because a squash landed on a base that
   never got there — the PR read as merged while `main` did not have the commits.
3. Prefer merge commits or rebase-and-merge onto `main` over squash when the branch carries
   design history worth preserving; squash is fine for single-purpose research dumps.

**Done when:** `git ls-remote --heads origin` shows `main` and open work branches only; this
rule is one paragraph in `README.md` under Contributing.

## Sequencing

```text
R0  separate research/          ← no dependencies; do first, alone
R1  scored.json + export script ← after R0 (paths)
R2  project skeleton            ← parallel with R1
R3  contract CI                 ← after R1 + R2
R4  split architecture/specs    ← after R3 (CI catches broken links from the split)
R5  branch hygiene              ← anytime after R0; cheapest last
```

R0 and R2 are the only ones that unblock M0. R4 is a readability refactor and can wait until
after the first runtime milestone if M0 pressure is higher — but it is cheaper before the docs
grow another 400 lines of concurrency prose.

## What this plan deliberately does not do

- **Does not reopen architectural decisions.** Blind Curator, bounded library, verifier
  isolation stay as they are. A refactor that "improves" those while moving files is a design
  change pretending to be janitorial work.
- **Does not start M0.** Scaffolding packages is not implementing nodes. The implementation
  plan remains the build order.
- **Does not convert research markdown into a database.** JSON exports are for diffability and
  CI, not for building a literature service.
- **Does not add a docs site.** MkDocs/Sphinx can wait until the split in R4 proves stable;
  generating a site over the current monolith would freeze a bad shape.

## Immediate next actions

1. Land R0 as its own PR: move research artifacts, delete `.xls`, fix links.
2. Land R2 next (or in parallel): `pyproject.toml` and empty `src/fandea/` packages.
3. Land R1 + R3 together: export script and the contract CI workflow.
4. Schedule R4 once CI is green; do the split as one PR per parent doc so review stays tractable.
5. Run R5 once the open agent branches from this cycle are confirmed idle.
