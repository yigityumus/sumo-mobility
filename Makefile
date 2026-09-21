SHELL := /bin/bash

UV ?= uv
DOCKER_COMPOSE ?= docker compose
DOCKER_API_IMAGE ?= campus-parking-api:local
DOCKER_SIMULATION_WORKER_IMAGE ?= campus-parking-simulation-worker:local
DOCKER_ANALYTICS_WORKER_IMAGE ?= campus-parking-analytics-worker:local
DOCKER_FRONTEND_IMAGE ?= campus-parking-frontend:local
SUMO_HOME ?= $(shell if [ -d "/usr/share/sumo/tools" ]; then printf "%s" "/usr/share/sumo"; fi)
HOST_UID ?= $(shell id -u)
HOST_GID ?= $(shell id -g)
export HOST_UID HOST_GID

UV_RUN := $(UV) run --group app --group scenario --group sumo --group api
PROJECT_PYTHONPATH := $(CURDIR)/backend
ifneq ($(strip $(SUMO_HOME)),)
PROJECT_PYTHONPATH := $(PROJECT_PYTHONPATH):$(SUMO_HOME)/tools
endif
export PYTHONPATH := $(PROJECT_PYTHONPATH):$(PYTHONPATH)

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Campus parking simulation"
	@echo
	@echo "Application:"
	@echo "  make setup             Install Python and frontend dependencies"
	@echo "  make run               Start backend and frontend development servers"
	@echo "  make run-backend       Start FastAPI on 127.0.0.1:8000"
	@echo "  make run-frontend      Start Vite on localhost:5173"
	@echo "  make run-simulation-worker  Consume queued SUMO jobs"
	@echo "  make run-analytics-worker   Consume analytics jobs"
	@echo "  make build             Build/check backend and frontend"
	@echo "  make build-backend     Compile and import-check the Python backend"
	@echo "  make build-frontend    Create the production frontend bundle"
	@echo "  make check             Run backend and frontend checks"
	@echo
	@echo "Docker (gateway, API, workers, RabbitMQ, PostgreSQL, and MinIO):"
	@echo "  make docker-check      Validate Docker, Compose, and daemon access"
	@echo "  make docker-build      Build the API, worker, and gateway images"
	@echo "  make docker-run        Start all services in the foreground"
	@echo "  make docker-up         Start all services in the background"
	@echo "  make docker-run-gui    Run with Linux X11 forwarding for SUMO GUI"
	@echo "  make docker-run-gui-macos  Run with macOS XQuartz forwarding for SUMO GUI"
	@echo "  make docker-logs       Follow container logs"
	@echo "  make docker-down       Stop services without deleting persistent data"
	@echo
	@echo "Safe cleanup (preserves all persistent service volumes):"
	@echo "  make clean             Delete caches, build artifacts, and macOS metadata"
	@echo "  make clean-cache       Delete Python/tool caches only"
	@echo "  make clean-build       Delete the frontend production bundle"
	@echo "  make deep-clean        Run clean and delete Python/Node dependencies"

.PHONY: setup
setup:
	@$(UV) sync --group app --group scenario --group sumo --group api
	@npm --prefix frontend install

.PHONY: run run-backend run-frontend api frontend
run:
	@set -euo pipefail; \
	$(UV_RUN) uvicorn services.api.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000 & \
	backend_pid=$$!; \
	trap 'kill $$backend_pid 2>/dev/null || true' EXIT INT TERM; \
	npm --prefix frontend run dev

run-backend api:
	@$(UV_RUN) uvicorn services.api.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000

run-frontend frontend:
	@npm --prefix frontend run dev

.PHONY: run-simulation-worker run-analytics-worker
run-simulation-worker:
	@$(UV_RUN) python -m services.simulation_worker.main

run-analytics-worker:
	@$(UV_RUN) python -m services.analytics_worker.main

.PHONY: build build-backend build-frontend frontend-build check check-backend check-frontend
build: build-backend build-frontend

build-backend:
	@$(UV_RUN) python -m compileall -q backend/services backend/domain backend/shared backend/sumo backend/tools
	@$(UV_RUN) python -c "from services.api.main import app; print(f'Backend import OK: {app.title}')"

build-frontend frontend-build:
	@npm --prefix frontend run build

check: check-backend check-frontend

check-backend:
	@command -v "$(UV)" >/dev/null 2>&1 || { echo "ERROR: uv was not found in PATH."; exit 1; }
	@if [ -n "$(SUMO_HOME)" ] && [ ! -d "$(SUMO_HOME)/tools" ]; then echo "ERROR: invalid SUMO_HOME: $(SUMO_HOME)"; exit 1; fi
	@for executable in sumo sumo-gui netconvert polyconvert; do command -v "$$executable" >/dev/null 2>&1 || { echo "ERROR: $$executable was not found in PATH."; exit 1; }; done
	@$(UV_RUN) python -c "import yaml, numpy, pandas, pika, traci, sumolib; from services.api.main import app; print('Backend dependencies OK')"

check-frontend:
	@npm --prefix frontend run typecheck

.PHONY: docker-check docker-image docker-build docker-run docker-up docker-run-gui docker-run-gui-macos docker-logs docker-down
docker-check:
	@command -v docker >/dev/null 2>&1 || { \
		echo "ERROR: Docker was not found in PATH."; \
		echo "Install Docker Engine and the Docker Compose plugin first."; \
		exit 1; \
	}
	@$(DOCKER_COMPOSE) version >/dev/null 2>&1 || { \
		echo "ERROR: '$(DOCKER_COMPOSE)' is unavailable."; \
		echo "Install or enable Docker Compose v2."; \
		exit 1; \
	}
	@docker info >/dev/null 2>&1 || { \
		echo "ERROR: Docker is installed, but this user cannot reach the Docker daemon."; \
		if snap list docker >/dev/null 2>&1; then \
			echo "This machine uses the Canonical Docker Snap. Configure non-root access with:"; \
			echo "  sudo addgroup --system docker"; \
			echo "  sudo adduser \"\$$USER\" docker"; \
			echo "  sudo snap disable docker"; \
			echo "  sudo snap enable docker"; \
			echo "Then log out and back in (or run 'newgrp docker') and retry 'make docker-check'."; \
		else \
			echo "Start the Docker daemon and add this user to the daemon's docker group."; \
		fi; \
		echo "Warning: membership in the docker group grants root-equivalent daemon access."; \
		exit 1; \
	}
	@echo "Docker client, Compose, and daemon access are working."

docker-image: docker-check
	@if ! docker image inspect "$(DOCKER_API_IMAGE)" >/dev/null 2>&1 \
		|| ! docker image inspect "$(DOCKER_SIMULATION_WORKER_IMAGE)" >/dev/null 2>&1 \
		|| ! docker image inspect "$(DOCKER_ANALYTICS_WORKER_IMAGE)" >/dev/null 2>&1 \
		|| ! docker image inspect "$(DOCKER_FRONTEND_IMAGE)" >/dev/null 2>&1; then \
		echo "One or more application images are missing; building them now."; \
		$(DOCKER_COMPOSE) build; \
	fi

docker-build: docker-check
	@$(DOCKER_COMPOSE) build

docker-run: docker-image
	@$(DOCKER_COMPOSE) up --no-build

docker-up: docker-image
	@$(DOCKER_COMPOSE) up --no-build --detach

docker-run-gui: docker-image
	@test -n "$$DISPLAY" || { echo "ERROR: DISPLAY is not set."; exit 1; }
	@test -n "$$XAUTHORITY" || { echo "ERROR: XAUTHORITY is not set."; exit 1; }
	@$(DOCKER_COMPOSE) -f compose.yaml -f compose.gui.yaml up --no-build

docker-run-gui-macos: docker-image
	@test "$$(uname -s)" = "Darwin" || { echo "ERROR: This target requires macOS. Use 'make docker-run-gui' on Linux."; exit 1; }
	@DOCKER_COMPOSE="$(DOCKER_COMPOSE)" bash scripts/docker-run-gui-macos.sh

docker-logs: docker-check
	@$(DOCKER_COMPOSE) logs --follow

docker-down: docker-check
	@$(DOCKER_COMPOSE) down

.PHONY: clean clean-cache clean-build deep-clean
clean-cache:
	@find backend -type d -name "__pycache__" -prune -exec rm -rf {} +
	@find backend -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete
	@rm -rf .pytest_cache .mypy_cache .ruff_cache frontend/.vite
	@echo "Deleted project caches. Saved models and simulation runs were preserved."

clean-build:
	@rm -rf frontend/dist
	@echo "Deleted reproducible build artifacts. Saved models and simulation runs were preserved."

clean: clean-cache clean-build
	@find . -type f \( -name ".DS_Store" -o -name "._*" -o -name ".LSOverride" \) -not -path "./.git/*" -delete
	@find . -type d \( -name "__MACOSX" -o -name ".AppleDouble" \) -not -path "./.git/*" -prune -exec rm -rf {} +
	@echo "Deleted macOS metadata files."
	@echo "Safe cleanup completed."

deep-clean: clean
	@rm -rf .venv backend/.venv node_modules frontend/node_modules
	@echo "Deleted project virtual environments and Node dependencies. Saved models and simulation runs were preserved."
