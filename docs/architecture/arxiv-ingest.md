# arXiv paper ingestion (Miner)

**Status:** shipped on the improvement plane as an offline **mine** path.
**Rule:** proposals only. No approved writes. No weight updates. No LLM extraction inside the job.

## What it does

1. Fetches Atom metadata from `export.arxiv.org` (ids or `search_query`).
2. Emits `Proposal(kind="mine")` rows with `payload.curation = "mined_from_paper"`.
3. Optionally materialises a **candidate** `SkillVersion` via `--submit`.
4. Leaves promotion behind the existing golden gate / review path.

The candidate is intentionally a stub: it records citation + abstract-bound intent so retrieval and later distill can find the paper. Executable steps and hard criteria are authored (human or success/failure distill) before promotion.

## CLI

```bash
# dry-run proposals for specific papers
recertia jobs run mine --arxiv-id 2605.22148 --arxiv-id 2607.01120 --dry-run

# search (max 50)
recertia jobs run mine --arxiv-query 'ti:"self-evolving" AND cat:cs.AI' --arxiv-max 5 --dry-run

# persist candidates (still not approved)
recertia jobs run mine --arxiv-id 2605.22148 --submit
```

Human-artifact mining is unchanged:

```bash
recertia jobs run mine --hint "docs/ops/runbook.md" --submit
```

## Contracts

`Curation` includes `mined_from_paper` (see `contracts/common.py`). Provenance on paper candidates uses that value and `derivation="mined_artifact"`.

## Honesty constraints

- Network is allowed; model calls are not part of this job.
- Rate limit: ≥3s between arXiv requests (client default).
- Library growth remains capped by Curator retirement and the active-set floor.
- Lift claims for paper-derived skills still require control-arm measurement (assumptions `a1` / weekly report).

## Follow-ups (not this PR)

- Optional PDF text extraction under the container sandbox (still proposal-only).
- Distill job that turns abstract claims into pitfall-oriented `failure_modes` + steps under the authoring prior.
- Semantic-plane facts keyed by `arxiv_id` for non-procedural recall.
