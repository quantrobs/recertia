# Changelog

## [Unreleased]

### Added

* **arXiv paper ingestion (Miner)** — `src/recertia/jobs/arxiv.py` Atom client; `mine_from_arxiv` proposals with `curation=mined_from_paper`; CLI `--arxiv-id` / `--arxiv-query` / `--arxiv-max` on `recertia jobs run mine`; optional `--submit` for candidate drafts only. Docs: `docs/architecture/arxiv-ingest.md`. Tests: `tests/unit/jobs/test_arxiv_ingest.py`.
* **Curation enum** — `mined_from_paper` added to `contracts/common.py`.

### Notes

* Paper candidates are retrieval stubs. Promotion still requires the golden gate; this path does not claim lift.
