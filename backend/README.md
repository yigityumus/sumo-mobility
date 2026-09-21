# Backend service map

The backend is a monorepo containing three separately deployable services plus
shared domain and infrastructure code.

```text
backend/
├── services/
│   ├── api/                 FastAPI HTTP service
│   ├── simulation_worker/   RabbitMQ consumer that runs SUMO
│   └── analytics_worker/    RabbitMQ consumer that builds analytics snapshots
├── domain/
│   ├── models/              Campus models, OSM, parking, detectors, exports
│   ├── simulations/         Simulation lifecycle and execution orchestration
│   ├── analytics/           Simulation output parsing and analytics payloads
│   ├── reference_data/      Sensor workbook ingestion and comparison series
│   └── demand/              Traffic-demand distribution models
├── shared/                  PostgreSQL, MinIO, RabbitMQ, config, worker runtime
│   └── migrations/          Versioned PostgreSQL migrations
└── sumo/
    ├── scenario/            Network, parking, detector, route input generators
    ├── controller/          TraCI runtime and agent managers
    └── config/              SUMO GUI configuration
```

Dependency direction is `services -> domain/shared` and `domain -> shared`.
Service packages must not import another service package. Services communicate
through RabbitMQ, PostgreSQL, and MinIO rather than Python calls.

The API and both workers have separate Docker image targets even though they
share one source repository and a common runtime base image.
