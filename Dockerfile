FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

ARG VITE_API_BASE_URL=
ARG VITE_DEFAULT_LAT=50.6110
ARG VITE_DEFAULT_LNG=3.1420
ARG VITE_DEFAULT_ZOOM=15
ARG VITE_MODEL_STORAGE=server

ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_DEFAULT_LAT=${VITE_DEFAULT_LAT} \
    VITE_DEFAULT_LNG=${VITE_DEFAULT_LNG} \
    VITE_DEFAULT_ZOOM=${VITE_DEFAULT_ZOOM} \
    VITE_MODEL_STORAGE=${VITE_MODEL_STORAGE}

RUN npm run typecheck && npm run build


FROM nginx:1.27-alpine AS frontend

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-builder /build/frontend/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1:8080/health || exit 1


FROM ubuntu:24.04 AS backend-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUMO_HOME=/usr/share/sumo \
    PYTHONPATH=/app/backend:/usr/share/sumo/tools \
    HOME=/tmp \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:${PATH}

COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        software-properties-common \
    && add-apt-repository --yes ppa:sumo/stable \
    && apt-get update \
    && apt-get install --yes --no-install-recommends \
        python3 \
        python3-venv \
        sumo \
        sumo-tools \
        tini \
    && rm -rf /var/lib/apt/lists/*

RUN command -v sumo \
    && command -v sumo-gui \
    && command -v netconvert \
    && command -v polyconvert \
    && python3 -c "import sumolib, traci"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache --no-install-project \
    --group app \
    --group scenario \
    --group sumo \
    --group api

COPY backend/ ./backend/

# Compose can run this image with the host's numeric UID/GID (for example,
# 501:20 on macOS rather than the image fallback 1000:1000). Keep the
# ephemeral workspace writable with normal /tmp sticky-directory semantics so
# every supported runtime identity can create its own model directories.
RUN install -d -m 1777 \
        /tmp/campus-simulation \
        /tmp/campus-simulation/models

# Compose replaces this with the host UID/GID. Numeric fallback IDs also work
# without creating a named account and avoid colliding with Ubuntu's existing
# UID/GID 1000 user and group.
USER 1000:1000

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]


FROM backend-runtime AS api

CMD ["uvicorn", "services.api.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]


FROM backend-runtime AS simulation-worker

WORKDIR /app/backend
CMD ["python3", "-m", "services.simulation_worker.main"]


FROM backend-runtime AS analytics-worker

WORKDIR /app/backend
CMD ["python3", "-m", "services.analytics_worker.main"]
