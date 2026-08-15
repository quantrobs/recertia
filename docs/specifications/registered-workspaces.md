# Registered workspaces (Pilot workdir binding)

Normative contracts for **registered host workspaces**: allowlisted absolute roots that
Pilot (and Programs) may bind as a run `workdir` without accepting arbitrary host escapes.
Companion docs: [product-console.md](product-console.md) §2.3, architecture
[product-console.md](../architecture/product-console.md), build order
[implementation-plan-registered-workspaces.md](../archive/2026-Q3/implementation-plan-registered-workspaces.md).

**Host path profile for this specification:** Windows. Roots are stored and displayed as
Windows absolute paths (drive-letter form). The API process MUST run on a host that can
`Path.resolve()` those paths (native Windows or equivalent). WSL-only `/mnt/d/...` roots are
out of scope for RW0–RW1; a later revision MAY add a POSIX profile.

## 1. Purpose

Today `POST /v1/runs` resolves `workdir` only under
`.recertia/workspaces/<tenant_id>/<run_id>/` and rejects absolute paths. That protects
tenants but makes Pilot unusable for real repositories. Registered workspaces restore
CLI-equivalent “run in this repo” behaviour through an **explicit, durable allowlist** per
tenant — not by reopening raw absolute `workdir` on create-run.

## 2. Definitions

| Term | Meaning |
| --- | --- |
| **Sandbox workdir** | Default create-run root: `{api_root}/workspaces/<tenant_id>/<run_id>/` |
| **Registered workspace** | Durable tenant-scoped record naming an allowlisted host directory |
| **Workspace id** | Stable slug used by clients (`recertia`, `my-app`) |
| **Host root** | Absolute Windows path of the registered directory after normalize+resolve |
| **Subpath** | Optional relative path under the host root used as the effective workdir |
| **Effective workdir** | Resolved directory the graph executor and validators use |

## 3. Data model

### 3.1 `RegisteredWorkspace`

| Field | Type | Rules |
| --- | --- | --- |
| `workspace_id` | string | `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` (same shape as `tenant_id`) |
| `tenant_id` | string | Owning tenant; immutable after create |
| `display_name` | string | Human label; 1–128 chars |
| `host_root` | string | Absolute Windows path; see §4 |
| `enabled` | bool | Disabled workspaces MUST NOT resolve on create/resume |
| `created_at` | datetime | UTC |
| `created_by` | string | Actor (`key_id`, console `user_id`, or CLI actor) |
| `notes` | string \| null | Optional operator note |

Persistence: SQLite under `{api_root}/workspaces_registry.sqlite` (or equivalent JSON store
with the same uniqueness). Primary key `(tenant_id, workspace_id)`.

Pydantic source of truth: `contracts/workspace.py` (ADR-0009); regenerate `schema/` when the
contract changes.

### 3.2 Run workdir metadata (`workdir.json`)

On create, persist enough to resume without re-trusting the client:

```json
{
  "kind": "registered",
  "workspace_id": "recertia",
  "subpath": "",
  "workdir": "D:\\src\\recertia",
  "host_root": "D:\\src\\recertia"
}
```

Sandbox runs keep:

```json
{
  "kind": "sandbox",
  "workdir": "D:\\…\\.recertia\\workspaces\\default\\run-abc"
}
```

`kind` is required for new writes. Readers MUST treat missing `kind` as `sandbox` and apply
legacy containment under the canonical run workspace (backward compatible).

## 4. Windows path rules

### 4.1 Accepted host roots

A host root is valid only if all of the following hold after strip of trailing separators:

1. Parsed with `pathlib.Path` on the API host.
2. `Path.is_absolute()` is true.
3. Form is **drive-letter absolute**: `^[A-Za-z]:[\\/].+` (after normalize).  
   - Examples accepted: `D:\src\recertia`, `D:/src/recertia`.  
   - Examples rejected: `recertia`, `\src\recertia`, `D:recertia` (drive-relative),
     `\\server\share\repo` (UNC — deferred), `\\?\D:\src\recertia` (extended-length —
     deferred).
4. `Path.resolve()` succeeds and the path exists as a **directory** at registration time.
5. The resolved path does not contain a null byte; registration MUST reject symlink cycles
   that prevent resolve (surface as 400).

Normalization before store:

- Convert `/` → `\` for storage display consistency on Windows.
- Store the **resolved** absolute path (no `.` / `..` components).
- Case: store resolved casing from the filesystem; comparisons for containment use
  `Path.resolve()` + `relative_to` (Windows case-insensitive semantics via the OS).

### 4.2 Subpath rules

`subpath` (API field `workdir` when `workspace_id` is set):

- MAY be omitted, `""`, or `.` → effective workdir = host root.
- MUST NOT be absolute (`Path.is_absolute()` false).
- MUST NOT escape the host root (`contained_path(host_root, *parts)` /
  `is_within`).
- Path separators MAY be `/` or `\`; split on both before join.
- Symlink escape outside host root MUST fail with 400 (same posture as
  `tests/unit/test_workspace_security.py`).

### 4.3 Forbidden create-run shapes

| Body | Result |
| --- | --- |
| `workdir: "D:\\src\\recertia"` without `workspace_id` | **400** — absolute paths still rejected |
| `workspace_id` unknown / other tenant / disabled | **404** or **403** (do not leak cross-tenant ids) |
| `workspace_id` + absolute `workdir` | **400** |
| `workspace_id` + `workdir` escaping host root | **400** |

## 5. HTTP API

Auth: existing `X-API-Key` and/or console session (`X-Recertia-Session`). Tenant resolution
unchanged (`X-Recertia-Tenant` / active tenant / key tenant).

### 5.1 Registry

| Method | Path | Scope / role | Purpose |
| --- | --- | --- | --- |
| `GET` | `/v1/workspaces` | `runs` or console operator+ | List enabled+disabled for caller tenant |
| `GET` | `/v1/workspaces/{workspace_id}` | `runs` or console operator+ | Fetch one |
| `POST` | `/v1/workspaces` | `admin` **or** console role `admin` | Register |
| `PATCH` | `/v1/workspaces/{workspace_id}` | `admin` **or** console role `admin` | Update `display_name`, `notes`, `enabled`; **not** `host_root` |
| `DELETE` | `/v1/workspaces/{workspace_id}` | `admin` **or** console role `admin` | Soft-delete → `enabled=false` (preferred) or hard delete if never used |

`POST` body:

```json
{
  "workspace_id": "recertia",
  "display_name": "example/recertia",
  "host_root": "D:\\src\\recertia",
  "notes": "main checkout"
}
```

Response 201 includes the stored record (resolved `host_root`). Re-registering the same
`workspace_id` with a different `host_root` MUST fail with **409**; operators disable and
create a new id, or use an explicit replace endpoint later (out of scope).

Changing `host_root` in place is forbidden in RW0–RW1 so resume metadata stays attributable.

### 5.2 Create run

Extend `RunCreate`:

| Field | Type | Meaning |
| --- | --- | --- |
| `workspace_id` | string \| null | When set, bind registered workspace |
| `workdir` | string \| null | If `workspace_id` set: subpath under host root. If unset: relative under sandbox (legacy) |

Resolution algorithm:

```text
if workspace_id:
    ws = load(tenant, workspace_id)  # enabled only
    root = Path(ws.host_root).resolve()
    effective = contained_path(root, subpath_parts(workdir))
else:
    effective = legacy _resolve_create_workdir(api_root, tenant, run_id, workdir)
persist workdir.json
mkdir effective if needed (sandbox only; registered root MUST already exist)
```

Registered roots MUST already exist; create-run MUST NOT create missing host roots (avoid
quietly materializing `D:\typo`). Sandbox behaviour unchanged (`mkdir`).

`exec` / `script` / local-exec gates are orthogonal and unchanged.

### 5.3 Resume

Resume MUST load `workdir.json`. For `kind=registered`:

1. Re-load workspace by `workspace_id` for the tenant.
2. If missing/disabled → **409** with clear detail (do not silently fall back to sandbox).
3. Re-resolve `subpath` under current `host_root`; if stored `host_root` ≠ registry
   `host_root` → **409** (registry mutated out of band / DB tamper).
4. Require `is_within(host_root, effective)` and directory exists.

### 5.4 Programs board

`POST /v1/programs/{id}/steps/{sid}/run` envelope/`run_create` MAY include `workspace_id` and
relative `workdir` (subpath). Semantics identical to §5.2. GP0 prereqs that require a
workdir treat `workspace_id` as satisfying the workdir presence check.

## 6. Pilot UX

### 6.1 Run mode fields

In Pilot → Run, add:

1. **Workspace** — `<select>`: `(sandbox — new empty workdir)` plus `GET /v1/workspaces`
   enabled entries (`display_name` + `workspace_id` + short `host_root`).
2. **Subpath** — text input, placeholder `(repo root)`, optional; sent as `workdir` only when
   a registered workspace is selected.
3. Helper text: registered binds edit the **real host tree**; sandbox is disposable.

Compose mode does not need these fields (drafts do not create runs).

### 6.2 Submit payload

```json
{
  "goal": { "...": "..." },
  "task_class": "repo-chore",
  "mode": "async",
  "budget": { "max_attempts": 2 },
  "workspace_id": "recertia",
  "workdir": ""
}
```

Sandbox selection omits `workspace_id` (and omits `workdir`, or sends relative sandbox
subdir if provided later).

### 6.3 Client-side validation

The console MUST refuse submit when:

- Subpath looks absolute (`/`, `\`, or `X:\` prefix), or
- Workspace select is sandbox but subpath is non-empty **and** absolute.

Server remains authoritative (PC posture: console refuses what API would reject).

### 6.4 Auth / Ops registration UI (minimum)

Auth or Ops panel: list workspaces; form to register (`workspace_id`, `display_name`,
`host_root`); disable toggle. No filesystem browser required in RW0 (paste path).

## 7. Security and threat model

| Threat | Control |
| --- | --- |
| Arbitrary host write via API | Absolute `workdir` without registry still 400; only admin registers roots |
| Cross-tenant bind | Registry keyed by tenant; resolve uses caller tenant only |
| Path escape via `..` / symlink | `contained_path` / resolve-before-check |
| Stale / moved repo | Resume 409 if root missing, disabled, or host_root drift |
| Accidental prod damage | UX warning; operators SHOULD use a throwaway branch; optional later
  `read_only` flag out of scope |
| Multi-tenant GA | Registered host roots on a shared API host are a **single-operator** feature;
  Phase-4 MUST re-review (likely disable host bind or require per-tenant volume mounts) |

Ledger: registration / disable SHOULD append an audit row (API key audit table or ledger
entry) with actor, tenant, workspace_id, host_root.

## 8. Conformance tests (RW-*)

| ID | Assertion |
| --- | --- |
| RW-1 | `POST /v1/runs` with absolute `workdir` and no `workspace_id` → 400 |
| RW-2 | Register `D:\…\repo`, create run with `workspace_id` → effective workdir is that root; criterion paths resolve there |
| RW-3 | `workdir` / subpath `..\\other` under registered root → 400 |
| RW-4 | Tenant B cannot list or bind tenant A’s `workspace_id` |
| RW-5 | Disable workspace → create/resume → 403/409 |
| RW-6 | Resume after create reuses same effective path; mutating registry host_root out of band → 409 |
| RW-7 | Pilot submit JSON includes `workspace_id` when select is non-sandbox (contract / static fixture or API-level test of payload builder) |
| RW-8 | Non-admin cannot `POST /v1/workspaces` |
| RW-9 | Mixed separators `subdir/foo` and `subdir\foo` resolve identically under host root |

Existing PC-1…PC-6 and `test_create_run_rejects_absolute_and_escaped_workdir` remain green.

## 9. Non-goals (RW0–RW1)

- UNC / `\\?\` extended paths
- In-browser native folder picker / OS file dialog
- Auto-clone from GitHub URL into sandbox
- Copy-on-write or snapshot of registered roots before solve
- Changing CLI `--workdir` (already free-form); CLI MAY later `--workspace-id` as sugar
- Replacing `repo_bindings` / `git_tip` (orthogonal; may point at the same disk tree)

## 10. Error surface (informative)

| HTTP | detail (substring) |
| --- | --- |
| 400 | `absolute paths rejected` / `workdir escapes` / `host_root must be a Windows drive-letter absolute directory` |
| 403 | `admin required to register workspace` / `workspace disabled` |
| 404 | `workspace not found` |
| 409 | `workspace_id exists` / `workspace host_root changed` / `registered workdir missing` |
