-- Reference sensor datasets and normalized observations.
CREATE TABLE real_world_datasets (
    id UUID PRIMARY KEY,
    original_filename TEXT NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    checksum_sha256 TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    etag TEXT,
    status TEXT NOT NULL,
    observation_count BIGINT NOT NULL DEFAULT 0,
    observation_start TIMESTAMP,
    observation_end TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ingested_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX real_world_datasets_status_idx
    ON real_world_datasets (status, updated_at DESC);

CREATE TABLE real_world_observations (
    dataset_id UUID NOT NULL REFERENCES real_world_datasets(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    segment_id TEXT NOT NULL,
    street TEXT NOT NULL,
    city TEXT NOT NULL,
    observed_at TIMESTAMP NOT NULL,
    pedestrian_count DOUBLE PRECISION NOT NULL,
    vehicle_count DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (dataset_id, row_number)
);

CREATE INDEX real_world_observations_segment_time_idx
    ON real_world_observations (segment_id, observed_at);
