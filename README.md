# Campus Parking Simulation

A browser-based campus model builder and parking simulation application. The
frontend uses React, Vite, Leaflet, and shadcn/ui. The production deployment
separates the web gateway, FastAPI, queued SUMO execution, analytics,
PostgreSQL, RabbitMQ, and MinIO. PostgreSQL stores queryable model/run metadata
and normalized sensor observations. MinIO is the authoritative S3-compatible
store for model inputs, complete SUMO artifacts, and original sensor
workbooks.

The former Streamlit application and shared, hard-coded SUMO scenario have
been removed. Every simulation is generated from the OSM source and parking
areas saved with its model.

## Features

- Draw a campus boundary or upload an OSM extract.
- Select and classify buildings and parking areas.
- Estimate parking capacities and save reusable campus models.
- Run without a building classification, or use arbitrary user-defined types to
  weight assigned destinations while unassigned buildings remain eligible with
  neutral random demand treatment.
- Configure independent vehicle and pedestrian demand profiles using constant,
  linear, normal, or Fourier distributions.
- Configure Fourier profiles with 1–16 hills, 1–16 harmonics, editable relative
  peak amplitudes, and widths recorded to 0.01 hours.
- Allocate independent pedestrians between selected Residential buildings and saved public-transport origins; parked drivers become pedestrians automatically.
- Choose pedestrian-reachable destination parking with a heterogeneous random-utility model that balances driving time, walking time, capacity, perceived availability, imperfect occupancy knowledge, and previous failures; also check eligible parking access roads encountered en route.
- Edit and snapshot parking-choice weights, occupancy knowledge, perception
  error, frustration response, and stochastic preference for each run.
- Queue multiple snapshotted setups, run them concurrently, remove waiting
  runs, or stop supported active headless runs.
- Run simulations using either headless SUMO or SUMO GUI, with an optional fast
  non-interacting pedestrian model.
- Track progress, status, parameters, parking occupancy, search duration,
  parking-attempt distribution, diagnostic warnings, and errors.
- Inspect a full-width, vertically scrollable Run History table whose columns
  can be resized and are remembered by the browser.
- Compare completed and partial runs on the Analytics page, including their
  selected demand distributions and complete Fourier parameters.
- Compare simulated E3 entry flow with uploaded real-world vehicle and
  pedestrian sensor data in raw or weekly-average mode, then download the exact
  plotted values as CSV.
- Export selected model data as a ZIP archive.

## Project structure

```text
.
├── backend/
│   ├── services/             Separately deployable API and worker entry points
│   │   ├── api/              FastAPI HTTP service
│   │   ├── simulation_worker/ RabbitMQ SUMO worker
│   │   └── analytics_worker/ RabbitMQ analytics worker
│   ├── domain/               Model, simulation, analytics, and sensor logic
│   ├── shared/               PostgreSQL, MinIO, RabbitMQ, and configuration
│   │   └── migrations/       Versioned PostgreSQL schema migrations
│   ├── sumo/                 TraCI controller, SUMO configuration, and runtime code
│   │   └── scenario/         Automatic network, parking, detector, and demand generators
│   └── tools/                Developer-only scenario inspection and debugging commands
├── frontend/                 React/Vite application
├── infrastructure/           RabbitMQ and MinIO initialization/configuration
├── scripts/                  Host launch and environment preflight helpers
├── Dockerfile                Backend and frontend production targets
├── compose.yaml              Containerized service deployment
├── compose.gui.yaml          Optional Linux X11 GUI overlay
├── compose.gui.macos.yaml    Optional macOS XQuartz GUI overlay
├── Makefile                  Docker and local-development commands
├── pyproject.toml            Python project and dependency groups
└── uv.lock                   Reproducible Python dependency lock
```

## Runtime architecture

```mermaid
flowchart LR
    Browser --> Gateway[nginx gateway]
    Gateway --> API[FastAPI]
    API --> PostgreSQL
    API --> RabbitMQ
    API --> MinIO
    RabbitMQ --> SumoWorker[SUMO workers]
    SumoWorker --> MinIO[MinIO object storage]
    SumoWorker --> PostgreSQL
    SumoWorker --> RabbitMQ
    RabbitMQ --> AnalyticsWorker[analytics workers]
    AnalyticsWorker --> MinIO
    AnalyticsWorker --> PostgreSQL
```

RabbitMQ is used as a work queue, not as an event-history platform. A
simulation request is persisted, acknowledged only after processing, retried
once after a worker failure, and then routed to a durable `.dead` queue if it
fails again. Kafka is intentionally absent because the current workload needs
task distribution and retries rather than replayable high-volume event streams.

The API is no longer occupied by long SUMO subprocesses. By default, two
simulation workers dispatch queued runs in FIFO order and run them concurrently.
You can add several setups from the Simulation page, close the browser, and
leave Docker and the computer running overnight. Each run snapshots its setup
when it is added, and a waiting run can be removed before SUMO starts it.

Set `SIMULATION_WORKER_CONCURRENCY` in the root `.env` file to tune capacity for
the available CPU and RAM. Queue position is dispatch order; with concurrent
workers, completion order can differ:

```bash
SIMULATION_WORKER_CONCURRENCY=4 docker compose up --detach --scale simulation-worker=4
```

All application processes are separately deployable and expose health checks.
The API and workers no longer share an artifact filesystem: each worker uses a
temporary local workspace and transfers inputs/results through MinIO. This
allows workers on different computers and maps cleanly to future Kubernetes
Deployments. PostgreSQL, RabbitMQ, and MinIO are the stateful services.

## Recommended: run everything with Docker

Docker Compose runs seven long-lived services plus one initialization job:

- `gateway`: nginx serves React and proxies `/api`;
- `api`: FastAPI handles short HTTP requests and creates jobs;
- `simulation-worker`: consumes durable jobs and runs SUMO/TraCI;
- `analytics-worker`: converts run outputs into cached analytics;
- `database`: PostgreSQL stores metadata and status;
- `rabbitmq`: durable work queues and dead-letter queues;
- `minio`: S3-compatible model, simulation artifact, and source-dataset
  storage;
- `minio-init`: creates both buckets and the restricted application account,
  then exits successfully.

The community MinIO server is built from its pinned official source tag because
the current community distribution is source-only. The build remains
reproducible and does not depend on an unversioned `latest` server image.

The API, simulation worker, and analytics worker have distinct image targets
built from a shared backend runtime containing Python, SUMO, TraCI,
`netconvert`, and `polyconvert`. This keeps deployment identities separate while
the remaining API-side detector preview still uses SUMO tooling. The gateway
image contains only nginx and the compiled frontend.

### 1. Requirements

Install Docker Engine and the Docker Compose plugin. Node.js, Python, `uv`, and
SUMO are not required on the host when using this workflow.

Confirm that Compose is available:

```bash
docker compose version
make docker-check
```

`make docker-check` also verifies that the current user can connect to the
Docker daemon. A working client version alone is not sufficient.

### 2. Create the environment file

```bash
cp .env.example .env
cp backend/.env.example backend/.env
```

Set different strong PostgreSQL, RabbitMQ, and MinIO passwords in `.env`. Then edit
`backend/.env` and replace the placeholder contact in `OSM_USER_AGENT` with a real email address.
Public Overpass API services expect an identifiable user agent.

### 3. Build and run

Build the application images after cloning the project or changing
source/dependency files:

```bash
make docker-build
```

Then start it in the background:

```bash
make docker-up
```

Use `make docker-run` instead when you want container logs in the foreground.
Both start commands reuse the existing image and build automatically only when
the image is missing.

The equivalent direct Compose commands are:

```bash
docker compose build
docker compose up --detach --no-build
```

Open:

- Application: <http://localhost:8000>
- Health check: <http://localhost:8000/api/health>
- API documentation: <http://localhost:8000/docs>
- MinIO administration console: <http://localhost:9001>

The MinIO console is bound to localhost and uses `MINIO_ROOT_USER` and
`MINIO_ROOT_PASSWORD`; its S3 API remains private to the Compose network.
PostgreSQL, RabbitMQ, FastAPI, and both workers are also private. On a remote
server, use an SSH tunnel rather than publishing the administration console:

```bash
ssh -L 9001:127.0.0.1:9001 your-user@your-server
```

Port 5173 is only used by the local Vite development server.

### Run in the background

```bash
make docker-up
make docker-logs
```

The equivalent Compose commands for an already-built image are:

```bash
docker compose up --detach --no-build
docker compose logs --follow
```

Stop the application with:

```bash
make docker-down
```

`docker compose down` removes the containers and Compose network, but it does
not remove MinIO objects, PostgreSQL records, or RabbitMQ messages.
Do not add `--volumes` when persistent service data must remain available.

### Change the host port

Port 8000 is the default. For example, to expose the application at
<http://localhost:8080>:

```bash
APP_PORT=8080 make docker-up
```

### Persistent application data

MinIO stores models, simulation artifacts, and original reference workbooks in
the named `minio_data` volume. PostgreSQL stores application metadata and
normalized sensor observations in `postgres_data`; RabbitMQ uses
`rabbitmq_data`. The API, workers, and initialization job have no host
data-directory mounts. Local files under `/tmp/campus-simulation` are
disposable workspaces rather than authoritative storage. Consequently, the
following operations preserve model data, simulation results, source datasets,
messages, and database records:

- rebuilding the image;
- restarting or replacing the container;
- running `make docker-down`;
- running `docker compose down`.

The Makefile passes the current Linux UID and GID to the stateless application
containers. When invoking Compose directly on a host account whose UID/GID is
not 1000, use:

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up --build
```

The legacy filesystem migration has been completed and is not part of normal
startup. New models and runs go directly to the `campus-simulation` bucket.
New sensor workbooks go through the upload API into the
`campus-reference-data` bucket and are normalized into PostgreSQL.

The application uses the restricted MinIO application account. Reserve the
root credentials for the console and administration. Back up all three named
volumes—`minio_data`, `postgres_data`, and `rabbitmq_data`—before a server move
or destructive maintenance. Never use `docker compose down --volumes` when
data must be preserved.

For a server deployment, set strong database, broker, and MinIO credentials in the
environment used by Compose. The defaults are for local development only.
Neither PostgreSQL nor RabbitMQ is published on a host port.

### SUMO GUI from Docker

SUMO GUI remains a desktop application; it is not rendered in the browser.
The platform-specific GUI overlays forward it from the same application
container to an X11 display.

#### Linux with X11 or XWayland

Check the graphical-session variables first:

```bash
echo "$DISPLAY"
echo "$XAUTHORITY"
test -f "$XAUTHORITY"
```

Then start the application with:

```bash
make docker-run-gui
```

This command uses both Compose files:

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
docker compose -f compose.yaml -f compose.gui.yaml up --no-build
```

You can now select **SUMO GUI** on the simulation page. Starting the regular
headless Docker configuration and then selecting SUMO GUI will fail because
the host display is intentionally not mounted.

#### macOS with Docker Desktop and XQuartz

Install XQuartz once:

```bash
brew install --cask xquartz
```

Log out and back in after installation. Start XQuartz, enable **Allow
connections from network clients** under **XQuartz > Settings > Security**, and
restart XQuartz.

Start the application with the macOS overlay:

```bash
make docker-run-gui-macos
```

The launcher enables XQuartz's indirect GLX renderer if necessary, restarts and
opens XQuartz, creates a temporary Xauthority cookie for Docker, verifies the
X11 connection from a simulation worker, and then starts the application. It
passes `DISPLAY=host.docker.internal:0` to the workers. The display may be
overridden for an unusual XQuartz setup with, for example,
`MACOS_DISPLAY=host.docker.internal:1 make docker-run-gui-macos`.

The temporary cookie is removed when the foreground Compose process exits. No
`xhost` command is required, and unrestricted `xhost +` access should not be
used.

See the official
[containerized SUMO GUI guide](https://sumo.dlr.de/docs/Tutorials/Containerized_SUMO_GUI.html).

## Local development without Docker

### Requirements

- Node.js 18 or later
- Python 3.12 or later
- `uv`
- SUMO, including `sumo`, `sumo-gui`, `netconvert`, `polyconvert`, and the
  Python tools normally found under `$SUMO_HOME/tools`
- PostgreSQL, only when local database synchronization is desired
- RabbitMQ, only when testing the separated workers locally
- MinIO, only when testing object-backed storage locally

On a standard Ubuntu SUMO installation, the Makefile automatically detects
`/usr/share/sumo`. Otherwise, export `SUMO_HOME` before running the project.

### First setup

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
make setup
make check
```

Set a real `OSM_USER_AGENT` contact in `backend/.env`. For a local PostgreSQL
instance, uncomment `DATABASE_URL` in the same file. Without object storage,
local development uses the configured temporary workspace and should not be
treated as persistent. Real-world sensor queries require PostgreSQL. Docker
Compose always enables PostgreSQL, RabbitMQ, and MinIO. When `RABBITMQ_URL` is
unset, FastAPI retains the convenient local fallback of executing the job as a
background task.

### Start both development servers

```bash
make run
```

Open <http://localhost:5173>. Vite serves the frontend and proxies `/api` to
FastAPI at `http://127.0.0.1:8000`.

To run the servers in separate terminals:

```bash
make run-backend
```

```bash
make run-frontend
```

When using local RabbitMQ, start these in two additional terminals:

```bash
make run-simulation-worker
make run-analytics-worker
```

### Start again after `make deep-clean`

```bash
make setup
make check
make run
```

`make setup` recreates the root `.venv` through `uv` and installs frontend npm
dependencies.

## Makefile command reference

Run `make help` to print the current command list.

### Docker commands

| Command | Purpose |
| --- | --- |
| `make docker-build` | Build the API, simulation-worker, analytics-worker, and gateway images. |
| `make docker-run` | Run in the foreground, building only if an image is missing. |
| `make docker-up` | Run in the background, building only if an image is missing. |
| `make docker-run-gui` | Run with the Linux X11 SUMO-GUI overlay. |
| `make docker-run-gui-macos` | Run with the macOS XQuartz SUMO-GUI overlay. |
| `make docker-logs` | Follow container logs. |
| `make docker-down` | Stop all services without deleting persistent data. |

### Local development and validation

| Command | Purpose |
| --- | --- |
| `make setup` | Install Python and frontend dependencies. |
| `make run` | Start FastAPI and Vite together. |
| `make run-backend` | Start FastAPI on port 8000. |
| `make run-frontend` | Start Vite on port 5173. |
| `make run-simulation-worker` | Consume queued SUMO runs. |
| `make run-analytics-worker` | Consume queued analytics jobs. |
| `make check` | Check backend dependencies and TypeScript. |
| `make build` | Import-check the backend and build the frontend. |
| `make build-backend` | Compile and import-check Python modules. |
| `make build-frontend` | Create `frontend/dist/`. |

### Safe cleanup

| Command | Purpose |
| --- | --- |
| `make clean-cache` | Delete Python and tool caches. |
| `make clean-build` | Delete `frontend/dist/`. |
| `make clean` | Remove caches, frontend build output, and macOS metadata files. |
| `make deep-clean` | Also delete Python virtual environments and `node_modules`. |

None of these cleanup targets delete either MinIO bucket or a service volume.
There is intentionally no Make target for deleting saved models, simulation
history, database storage, or physical-sensor workbooks.

## Application workflow

1. Draw a polygon or rectangle around the campus, or upload an OSM XML file.
2. Load the buildings and polygonal `amenity=parking` areas.
3. Select buildings and parking areas. Building classifications are optional;
   parking classifications can be used to organize and configure parking.
4. Save the model. Its source OSM extract is retained with it.
5. Open the model's Simulation page and configure agent totals, pedestrian
   sources, duration, demand distributions, parking-search behavior, pedestrian
   behavior, and execution mode.
6. Add the setup to the durable queue. The model and settings are snapshotted,
   so the controls can immediately be changed to queue another independent run.
7. Monitor the queue and Run History. Waiting runs can be removed; supported
   active headless runs can be stopped while preserving partial diagnostics.
8. Open Analytics to inspect one run, overlay up to four additional runs, or
   compare a simulation detector with an uploaded real-world sensor dataset.

### Current Simulation-page defaults

These are initial values for a newly opened Simulation page. They do not modify
queued runs or historical snapshots.

| Setting | Default |
| --- | --- |
| Total people | 16,000 |
| Arriving by car | 3,000 people/vehicles |
| Independent walking arrivals | 13,000 people |
| Duration | 12 hours |
| Arriving-by-car profile | Normal distribution |
| Independent-pedestrian profile | Normal distribution |
| Building demand classification | None |
| Pedestrian behavior | Interactive SUMO striping model |
| Execution mode | Headless SUMO |
| Full TraCI diagnostic trace | Off |
| Parking perception error | 0.15 |

The independent-walker count is always `total people - arriving by car`.
Parked drivers are the same car-arriving people changing travel mode after
parking, so they are not added to the total a second time. Independent walkers
must be allocated exactly between the available Residential-building and
public-transport origin sources. The corresponding input is disabled when the
selected model cannot provide that source.

When Fourier is selected for pedestrians, its initial editor preset is 16
evenly spaced peaks, width `0.3` hours, and 10 harmonics, with relative peak
amplitudes:

```text
20%, 75%, 10%, 15%, 100%, 10%, 40%, 100%,
10%, 15%, 75%, 10%, 65%, 40%, 15%, 10%
```

These percentages describe relative peak heights; the generated departure
curve is normalized so its area produces the requested pedestrian total.

### Building-classification behavior

A classification is not required to run a simulation. Classification names and
destination type names are user-defined; a type named `Teaching` is not
required. With no selected classification, all selected, reachable buildings
are eligible destinations with equal random treatment.

When a classification is selected, assigned buildings use the pedestrian and
vehicle demand weights of their type. Unassigned selected buildings remain
eligible with neutral 50/50 weights instead of being rejected or omitted.
`Residential` is the only reserved type name, and only for the optional
residential pedestrian-origin source. Matching is case-insensitive; the source
is disabled when the selected classification has no Residential type or no
selected building assigned to it.

### Analytics and real-world sensor comparison

Analytics preserves and displays each run's vehicle and pedestrian distribution.
For Fourier distributions it also displays the number of peaks, width,
harmonics, and every peak amplitude. Available charts cover parking occupancy,
distinct parking areas attempted, recorded search time, vehicle journey-stage
duration, detector entry counts, and grouped debug messages. Summary percentiles
describe individual records across the full run, while line-chart points are
time-bin averages; a full-run percentile can therefore exceed every plotted bin
average.

An E3 detector group that measures both vehicles and pedestrians can be paired
with an ingested physical sensor. Simulation entries are rebinned into
900-second (15-minute) intervals. Raw mode uses a selected real date/time;
weekly-average mode averages the same weekday and 15-minute time slot across all
available weeks. The graph uses hourly-normalized flow rates so datasets with
different native interval lengths remain comparable:

```text
flow_agents_per_hour = interval_count * 3600 / interval_seconds
```

For a 15-minute interval, hourly flow is therefore four times the actual
interval count. The downloadable comparison CSV includes both forms:

- `*_simulation_interval_count`: simulated entries allocated to that interval;
- `*_simulation_flow_agents_per_hour`: the plotted simulated hourly rate;
- `*_real_world_interval_count`: the raw count, or the mean interval count in
  weekly-average mode;
- `*_real_world_flow_agents_per_hour`: the plotted physical-sensor hourly rate;
- `*_real_world_sample_count`: the number of physical observations contributing
  to the point (`1` in raw mode and potentially several weeks in weekly-average
  mode), not a pedestrian or vehicle count.

### Automated flow calibration

The Simulation page has a **Locked Fourier flow calibration** section. A
calibration snapshots the complete setup and runs the requested number of
iterations sequentially. Agent counts, classification, source allocation,
calendar window, behavior, random seed, model/map, peak count, peak width, and
harmonics remain fixed. Only the selected Fourier `peak_heights` values change.

After iteration `n`, the run duration is split into one equal-width cell per
peak. For every cell the weekly-average physical flow and simulated detector
flow are averaged. The first update uses the proportional ratio:

```text
proposed percentage = previous percentage * (real flow / simulated flow)
```

Once a peak has at least three distinct observed input/output pairs, the
calibrator fits a bounded Hill response and inverts it to estimate the input
needed for the physical target. If that fit has insufficient explanatory power,
it uses measured local elasticity; otherwise it retains the proportional
fallback. This accounts for the fact that doubling an input percentage may
produce much less than twice the detector flow near saturation.

The proposed change is rounded to a user-configurable percentage-point step
(1% by default), with every nonzero change at least one step. The existing
Fourier percentage range of 0–300% is enforced. A calibration
stops with a diagnostic when physical flow is positive but the simulation
detector records zero for the selected subject, because that ratio is not
finite. With 16 peaks over 12 hours, cells are 45 minutes wide. Fourier peaks
are centered in their cells, so a 07:00 start places the first center at
07:22:30; 07:45 is the end of the first cell.

All iterations share a fixed simulation seed so random route and destination
sampling cannot masquerade as a Fourier improvement. A calibration queues only
one dependent iteration at a time. The second simulation worker remains
available for another independent simulation or calibration.

The defaults reproduce the Cite Scientifique Test 2 experiment: 16,000 people,
3,000 cars, 4,000 residential walkers, Usage Policy destinations, Fourier
demand, fast pedestrians, deterministic parking choice, and 07:00–19:00 on
Monday 19 January 2026. The comparison uses the Avenue Paul Langevin vehicle
sensor's Monday 07:00 weekly average:

```bash
python3 scripts/calibrate_flow.py --iterations 10 --step-percentage 1 --detector-name "Paul Langevin"
```

The script calls the same persistent calibration API as the page. Use
`--dry-run` to resolve and print the complete locked request without queuing
SUMO. Pass `--subject pedestrians` or `--subject both` as needed, and use
`--vehicle-fourier-file` / `--pedestrian-fourier-file` to provide initial JSON
profiles. `--output-file result.json` writes the completed session metadata.

On the Analytics page, selecting any calibration run opens its calibration
group. Every iteration can be selected or cleared independently. The input vs
output tab shows the generated demand profile and detector response for both
vehicles and pedestrians. Iteration progress shows a selected peak's input,
output, physical target, and group error curves. The statistics tab includes
NRMSE, NMAE, MAPE, bias, shape and volume errors, correlation, Nash-Sutcliffe
efficiency, and detailed per-peak response-model diagnostics.

## Persistent models, runs, and sensor data

For new sensor data, upload a workbook through
`POST /api/analytics/real-world/datasets` in the API documentation, or use:

```bash
curl --fail --form "file=@sensor-export.xlsx" \
  http://localhost:8000/api/analytics/real-world/datasets
```

The original workbook is retained in the `campus-reference-data` MinIO bucket.
Its parsed observations and dataset status are stored in PostgreSQL. An upload
whose content already exists is deduplicated by SHA-256 checksum. The current
supported source format is `.xlsx`, up to `MAX_REFERENCE_UPLOAD_MB`.

Models use keys beneath:

```text
models/<model-id>/
```

and every run stores immutable inputs and outputs beneath:

```text
models/<model-id>/simulations/<run-id>/
```

Important generated inputs include:

- `inputs/source.osm.xml`: the model's source map snapshot;
- `inputs/source.osm.xml.gz`: its compressed SUMO conversion input;
- `inputs/model.net.xml.gz`: SUMO road, lane, junction, and connection network;
- `inputs/model.poly.xml.gz`: optional visual polygons;
- `inputs/passenger.rou.xml` and `inputs/pedestrian.rou.xml`: generated demand;
- `inputs/vehicle_parking_plan.csv`: destination-specific parking candidates, initial behavioral choice scores, perceived availability, and driver profile;
- `inputs/simulation.sumocfg`: the run-specific SUMO configuration;
- `simulation.log`: the application/worker execution log parsed into grouped
  warnings and errors by the Analytics debug menu;
- `outputs/sumo.log`: SUMO's dedicated warning and error log;
- `outputs/traci.trace.py`: the optional replayable TraCI command trace when diagnostic tracing is enabled;
- `outputs/parking_events.csv`: parking attempts, target changes, assignments, and exhausted fallback lists;
- `outputs/search_times.csv`: per-vehicle search outcome and distinct logical parking areas attempted;
- `outputs/sumo_process.json`: the SUMO child-process return code, terminating signal, and controller error;
- `outputs/detectors/e2_pedestrians.xml`: direction-independent pedestrian entries for logical E3 areas (one safe lane-area zone per sidewalk lane);
- `outputs/sumo_recoveries.csv`: any bounded checkpoint recoveries and the final-stage pedestrians quarantined after a SUMO `SIGSEGV` or `SIGBUS`;
- `outputs/sumo_recovery_state.xml.gz`: the latest rolling SUMO recovery checkpoint;
- `outputs/*.attempt-<n>.*`: native SUMO logs and partial outputs retained from a crashed attempt before recovery;
- `parking_areas.yaml`: the parking selection and capacity snapshot.

In Docker, these relative paths become object keys in the
`campus-simulation` MinIO bucket; workers use temporary local directories while
processing. The application does not use a shared project-wide network or a
shared `.sumocfg` file.

PostgreSQL stores model metadata, run parameters/status/progress, an artifact
inventory, reference-dataset metadata, and normalized sensor observations. It
deliberately does not store the large XML, CSV, map, log, or original workbook
contents. Database records instead reference authoritative MinIO object keys.

## Configuration

### Backend: `backend/.env`

```dotenv
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
OVERPASS_ENDPOINTS=https://overpass.private.coffee/api/interpreter,https://maps.mail.ru/osm/tools/overpass/api/interpreter,https://overpass-api.de/api/interpreter
OSM_USER_AGENT=sumo-area-builder/0.2 (contact: your-email@example.com)
OVERPASS_TIMEOUT_SECONDS=90
CACHE_TTL_SECONDS=600
MAX_BOUNDARY_VERTICES=500
MAX_BOUNDARY_SPAN_DEGREES=0.25
MODEL_STORAGE_DIR=/tmp/campus-simulation/models
# Optional outside Docker; Compose supplies the endpoint and credentials:
# OBJECT_STORAGE_ENDPOINT=127.0.0.1:9000
# OBJECT_STORAGE_ACCESS_KEY=campus_app
# OBJECT_STORAGE_SECRET_KEY=replace-with-the-MinIO-application-password
OBJECT_STORAGE_BUCKET=campus-simulation
OBJECT_STORAGE_SECURE=false
OBJECT_STORAGE_PREFIX=models
REFERENCE_DATA_BUCKET=campus-reference-data
REFERENCE_DATA_PREFIX=raw
MAX_REFERENCE_UPLOAD_MB=100
# Optional outside Docker; Compose sets this automatically:
# DATABASE_URL=postgresql://campus_app:password@127.0.0.1:5432/campus_simulation
# RABBITMQ_URL=amqp://campus_app:password@127.0.0.1:5672/%2F
DATABASE_POOL_MIN_SIZE=1
DATABASE_POOL_MAX_SIZE=5
DATABASE_CONNECT_TIMEOUT_SECONDS=10
SIMULATION_QUEUE_NAME=simulation.jobs
SIMULATION_WORKER_CONCURRENCY=2
ANALYTICS_QUEUE_NAME=analytics.jobs
```

`MODEL_STORAGE_DIR` is an ephemeral workspace, not persistent storage. Docker
Compose configures PostgreSQL, RabbitMQ, and both MinIO buckets automatically;
its API and workers do not mount a host data directory. Compose accepts the
database, RabbitMQ, and MinIO credentials; bucket names; `APP_PORT`;
`MINIO_CONSOLE_PORT`; `ALLOWED_ORIGINS`; and
`SIMULATION_WORKER_CONCURRENCY` from the root environment. Back up all storage
layers: use `pg_dump` for PostgreSQL and preserve both the MinIO and RabbitMQ
volumes.

### Frontend: `frontend/.env`

```dotenv
VITE_API_BASE_URL=
VITE_DEFAULT_LAT=50.6110
VITE_DEFAULT_LNG=3.1420
VITE_DEFAULT_ZOOM=15
VITE_MODEL_STORAGE=server
```

Leave `VITE_API_BASE_URL` empty for same-origin Docker requests and for local
Vite proxying. `VITE_MODEL_STORAGE=server` keeps models in FastAPI storage;
`local` switches to browser IndexedDB and is intended only as a fallback.

## Troubleshooting

### Docker build does not start

Run the project preflight check:

```bash
make docker-check
```

You can also check each layer directly:

```bash
docker --version
docker compose version
docker info
```

Then inspect the build without starting the application:

```bash
make docker-build
```

#### Canonical Docker Snap: permission denied on `docker.sock`

The Docker Snap initially permits daemon access only through root. To use the
project's normal `make docker-*` commands without `sudo`, create the Docker
group, add your account, and restart the Snap so it recreates its socket with
the new group:

```bash
sudo addgroup --system docker
sudo adduser "$USER" docker
sudo snap disable docker
sudo snap enable docker
```

Then log out and back in. For the current terminal, `newgrp docker` can be used
instead. Verify the result before building:

```bash
newgrp docker
docker info
make docker-check
make docker-build
```

Membership in the `docker` group grants root-equivalent access to the Docker
daemon. Do not work around the problem by running the whole project with
`sudo make`; root-owned build and cache files can break later development.

#### Docker reports `no space left on device`

Inspect Docker and filesystem usage first:

```bash
docker system df
df -h /
```

BuildKit cache is reproducible and can be removed without deleting the built
application image, containers, volumes, models, or simulation outputs:

```bash
docker builder prune --force
```

Afterward, start the existing image without rebuilding it:

```bash
make docker-up
```

### Port 8000 is already in use

Choose another host port:

```bash
APP_PORT=8080 make docker-up
```

### SUMO GUI does not open from Docker

- On Linux, start with `make docker-run-gui`, verify that `DISPLAY` is non-empty,
  and verify that `XAUTHORITY` names an existing readable file.
- On macOS, enable **Allow connections from network clients** in XQuartz,
  restart XQuartz, and start with `make docker-run-gui-macos`. The launcher
  enables indirect GLX and verifies both the authorization cookie and the
  worker's X11 connection.
- On macOS, verify that the worker receives
  `DISPLAY=host.docker.internal:0` and `XAUTHORITY=/tmp/.sumo-xquartz.xauth`
  unless `MACOS_DISPLAY` was overridden.
- Confirm that the container user uses the host UID/GID.
- Review the backend output with `make docker-logs`.

### A simulation fails

Open its Analytics debug menu to inspect grouped SUMO warnings and errors. The
complete per-run log is also stored as `simulation.log` in that run directory.

## Notes

- Destination parking uses a reproducible weighted random-utility choice rather
  than a strict nearest-lot or capacity-band order. Each driver belongs to a
  heterogeneous behavioral profile and trades off driving time, walking time,
  total capacity, perceived absolute and relative free space, and random
  preference. Remote occupancy knowledge is imperfect; after failed visits,
  availability matters more. A driver directly observes and checks an untried,
  destination-compatible parking area when its access edge lies on the actual
  route. The default coefficients are behavioral assumptions and should be
  calibrated against observed parking choices when empirical data is available.
- Every newly queued run receives a fresh recorded random seed. The seed drives
  demand assignment, parking choice, parking duration, and SUMO, so repeated
  setups vary while an individual run remains reproducible. Parking-search
  weights and the knowledge, perception, frustration, and randomness parameters
  are editable on the Simulation page and are snapshotted with the run.
- Fourier peak width accepts 0.01-hour precision and up to 16 hills. A 0.01-hour
  width is only 36 seconds; with a finite number of Fourier harmonics, very narrow
  requested peaks are necessarily smoothed. Use the preview and increase the
  harmonic count when the resulting curve is broader than intended.
- Each simulation worker processes one run at a time; add workers only within
  the server's CPU and RAM capacity.
- Full TraCI command/getter tracing is disabled by default because it can add
  gigabytes of output. Enable it per run only when reproducing a SUMO failure.
- `Fast` pedestrian behavior uses SUMO's non-interacting pedestrian model. It
  preserves routes and detector counting but intentionally omits crowd and
  pedestrian/vehicle interaction behavior.
- Keep SUMO GUI open until its simulation finishes.
- The frontend contains a runtime workaround for the `leaflet-draw` 1.0.4
  `readableArea` strict-mode bug; do not patch `node_modules` manually.
