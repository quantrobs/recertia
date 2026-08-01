-- M9 store bootstrap (SQLite dialect for CI / local snapshots)
CREATE TABLE IF NOT EXISTS skills_meta (
    skill_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    scope TEXT NOT NULL DEFAULT 'project',
    task_class TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    PRIMARY KEY (skill_id, version)
);

CREATE TABLE IF NOT EXISTS facts_meta (
    fact_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    slug TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    plane TEXT NOT NULL,
    object_id TEXT NOT NULL,
    dims INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    PRIMARY KEY (plane, object_id)
);

CREATE TABLE IF NOT EXISTS run_checkpoints (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    node TEXT NOT NULL,
    next_node TEXT,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
