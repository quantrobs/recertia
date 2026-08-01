# Incident tabletop (operator GA)

One documented incident review is a Phase‑1 GA criterion. Run this tabletop even when
no production incident has occurred — the point is to exercise the restore path.

## Scenario

An operator notices a run stuck in `unsolved` after a tool timeout, and the workdir
looks partially written.

## Walkthrough

1. Identify the run id from the CLI/API response or OTel `run.finished` event.
2. Open the hash-chain ledger under `.recertia/runs/<tenant>/ledger.jsonl` (or the
   tenant path used by the API) and locate entries for that run.
3. Read the transcript for the failing attempt; note the failure class from
   `classify_failure`.
4. Confirm the run manifest pins (provider, model id, index snapshot, library commit).
5. Restore from the last `.recertia/` backup (nightly tar / volume snapshot).
6. Re-run `recertia gc --older-than-days 14` only after restore verification.
7. Log the tabletop in an ops note: date, run id, restore source, time-to-recover,
   and any control-plane fix preferred over prose.

## Pass criteria

- Ledger → transcript → failure class path is navigable without tribal knowledge.
- Restore produces a usable `.recertia/` tree.
- Follow-up is a concrete control-plane change or an explicit accepted risk.
