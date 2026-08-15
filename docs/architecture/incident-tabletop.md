# Incident tabletop (operator GA)

One documented incident review is a Phase‑1 GA criterion. Run this tabletop even when
no production incident has occurred — the point is to exercise the restore path.

## Scenario

An operator notices a run stuck in `unsolved` after a tool timeout, and the workdir
looks partially written.

## Walkthrough

1. Identify the run id from the CLI/API response or OTel `run.finished` event.
2. Run `recertia tabletop <run_id> --runs-root .recertia --restore-from <backup.tar.gz> --follow-up "…" --output tabletop.json` (or walk the steps below by hand).
3. Open the hash-chain ledger under `.recertia/runs/<tenant>/ledger.jsonl` (or the
   tenant path used by the API) and locate entries for that run.
4. Read the transcript for the failing attempt; note the failure class from
   `classify_failure`.
5. Confirm the run manifest pins (provider, model id, index snapshot, library commit).
6. Restore from the last `.recertia/` backup (`recertia restore ARCHIVE` or nightly tar / volume snapshot).
7. Re-run `recertia gc --older-than-days 14` only after restore verification.
8. Keep the tabletop JSON: date, run id, restore source, time-to-recover, follow-up.
   `ga_claimed` MUST stay false until the four-week soak gate also passes.

## Pass criteria

- Ledger → transcript → failure class path is navigable without tribal knowledge.
- Restore produces a usable `.recertia/` tree.
- Follow-up is a concrete control-plane change or an explicit accepted risk.
