-- Persistent multi-run Fourier peak calibration sessions.
CREATE TABLE flow_calibrations (
    id UUID PRIMARY KEY,
    model_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE INDEX flow_calibrations_model_created_idx
    ON flow_calibrations (model_id, created_at DESC);

CREATE INDEX flow_calibrations_status_idx
    ON flow_calibrations (status, updated_at DESC);
