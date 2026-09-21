-- Initial application metadata schema.
CREATE TABLE campus_models (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    storage_path TEXT NOT NULL,
    payload JSONB NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE simulation_runs (
    id UUID PRIMARY KEY,
    model_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    vehicle_count INTEGER NOT NULL DEFAULT 0,
    pedestrian_count INTEGER NOT NULL DEFAULT 0,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    simulation_start_at TIMESTAMPTZ,
    simulation_end_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    progress_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    failure_reason TEXT,
    storage_path TEXT NOT NULL,
    payload JSONB NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX simulation_runs_model_created_idx
    ON simulation_runs (model_id, created_at DESC);

CREATE INDEX simulation_runs_status_idx
    ON simulation_runs (status);

CREATE TABLE simulation_artifacts (
    run_id UUID NOT NULL REFERENCES simulation_runs(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    modified_at TIMESTAMPTZ NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, relative_path)
);
