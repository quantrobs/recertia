# Registered workspaces — implementation plan

Build order for Pilot workdir binding via allowlisted Windows host roots.
Normative contracts: [`specifications/registered-workspaces.md`](specifications/registered-workspaces.md).
Architecture note: [`architecture/product-console.md`](architecture/product-console.md) §3.1 Workdir picker.

## Guiding rules

1. **No raw absolute `workdir` on create-run.** Registry is the only API path to host trees.
2. **Preserve sandbox default.** Omitting `workspace_id` keeps today’s sandbox behaviour.
3. **Windows drive-letter roots first.** Reject UNC / extended-length until a later revision.
4. **Admin registers; runners bind.**
5. **Resume is strict.** Disabled, missing, or drifted `host_root` → hard fail (409).

## Milestones

```text
RW0  Registry + create/resume resolution + tests     Implemented
RW1  Pilot UI (select + subpath) + register form     Implemented
RW2  Docs/go-live polish + optional CLI sugar        Implemented
```

## RW0 — Registry and run binding

- Contract `RegisteredWorkspace` in `contracts/workspace.py`
- Store under api root; path helpers for Windows roots
- `RunCreate.workspace_id`; resolve and persist `workdir.json` with kind
- Resume enforcement; CRUD routes for workspaces

## RW1 — Pilot UI

- Workspace select + subpath in Pilot SPA
- Register form under Auth/Ops
- Programs step run envelope passes workspace_id

## RW2 — Operator docs and CLI sugar

- go-live.md Console section with register → Pilot steps
- Optional `recertia workspaces register|list` and `run --workspace-id`

## Risks

| Risk | Mitigation |
| --- | --- |
| API under WSL cannot see `D:\…` | Document run uvicorn on Windows for this feature |
| Container bind-mount of host repo | Document Docker Desktop file sharing grant |
| Operators edit main branch in place | UX warning; recommend feature branch |
