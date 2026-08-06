# Research artifacts

Scored preprint surveys and score-10 bibliography extracts. **Not normative** — design
impact is recorded in [`docs/references.md`](../docs/references.md) and
[`docs/assumptions.md`](../docs/assumptions.md).

| Path | Contents |
| --- | --- |
| `preprints-self-improving-agents.xlsx` / `.scored.json` | ~117-paper applicability survey |
| `preprints-score10-reference-lists.xlsx` / `.scored.json` | Score-10 paper reference-list extracts |
| [`score10-references/`](score10-references/) | Per-paper bibliography markdown + combined JSON |

## Git LFS

Spreadsheets, `*.scored.json`, and `score10-references/score10-references.json` are stored
with [Git LFS](https://git-lfs.com/). Clone/fetch needs `git lfs install` (and network access
to the LFS endpoint). Without LFS you will only see pointer files.

```bash
git lfs install
git lfs pull
```
