-- Object-storage and worker-coordination extensions.
ALTER TABLE simulation_runs
    ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS worker_id TEXT,
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS worker_heartbeat_at TIMESTAMPTZ;

ALTER TABLE simulation_artifacts
    ADD COLUMN IF NOT EXISTS storage_backend TEXT NOT NULL DEFAULT 'filesystem',
    ADD COLUMN IF NOT EXISTS object_key TEXT,
    ADD COLUMN IF NOT EXISTS etag TEXT;

CREATE INDEX IF NOT EXISTS simulation_runs_worker_heartbeat_idx
    ON simulation_runs (status, worker_heartbeat_at)
    WHERE status = 'running';
