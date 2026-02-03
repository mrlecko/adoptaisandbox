# CSV Analyst Chat - Makefile
# Common development tasks

.PHONY: help dev test clean install build-runner-test test-runner test-agent-server run-agent run-agent-dev agent-venv

# Default target
.DEFAULT_GOAL := help

AGENT_VENV := agent-server/.venv
AGENT_PYTHON := $(AGENT_VENV)/bin/python
AGENT_PIP := $(AGENT_VENV)/bin/pip
AGENT_PYTEST := $(AGENT_VENV)/bin/pytest
AGENT_UVICORN := $(AGENT_VENV)/bin/uvicorn
AGENT_VENV_STAMP := $(AGENT_VENV)/.deps.stamp

##@ General

help: ## Display this help message
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Development

install: ## Install dependencies (agent-server and UI)
	@echo "Installing agent-server dependencies..."
	$(MAKE) agent-venv
	@echo "Installing UI dependencies..."
	cd ui && npm install
	@echo "✓ Dependencies installed"

$(AGENT_VENV_STAMP): agent-server/requirements.txt
	@if [ ! -x "$(AGENT_PYTHON)" ]; then \
		echo "Creating agent-server virtualenv..."; \
		python3 -m venv $(AGENT_VENV); \
	fi
	@$(AGENT_PIP) install -r agent-server/requirements.txt
	@touch $(AGENT_VENV_STAMP)

agent-venv: $(AGENT_VENV_STAMP) ## Ensure agent-server virtualenv exists and deps are installed
	@echo "✓ Agent virtualenv ready at $(AGENT_VENV)"

dev: ## Start local development environment (docker-compose)
	@echo "Starting local development environment..."
	docker compose up --build
	@echo "✓ Services running at http://localhost:3000"

dev-down: ## Stop local development environment
	docker compose down

dev-logs: ## View logs from development environment
	docker compose logs -f

run-agent: agent-venv ## Run single-file FastAPI agent server
	$(AGENT_UVICORN) app.main:app --app-dir agent-server --host 0.0.0.0 --port 8000

run-agent-dev: agent-venv ## Run single-file FastAPI agent server with auto-reload
	$(AGENT_UVICORN) app.main:app --app-dir agent-server --host 0.0.0.0 --port 8000 --reload

run-agent-microsandbox: agent-venv ## Run agent server with MicroSandbox provider
	SANDBOX_PROVIDER=microsandbox $(AGENT_UVICORN) app.main:app --app-dir agent-server --host 0.0.0.0 --port 8000 --reload

##@ Testing

test: agent-venv ## Run all tests
	@echo "Running all tests..."
	$(AGENT_PYTEST) tests/ -v
	@echo "✓ All tests passed"

test-runner: agent-venv build-runner-test ## Run runner integration tests (requires Docker)
	@echo "Running runner integration tests..."
	RUNNER_TEST_IMAGE=csv-analyst-runner:test $(AGENT_PYTEST) tests/integration/test_runner_container.py tests/integration/test_docker_executor_integration.py -v

test-agent-server: agent-venv ## Run single-file agent server integration tests
	@echo "Running agent server integration tests..."
	$(AGENT_PYTEST) tests/integration/test_agent_server_singlefile.py -v

test-unit: agent-venv ## Run unit tests only
	@echo "Running unit tests..."
	$(AGENT_PYTEST) tests/unit/ -v

test-integration: agent-venv ## Run integration tests only
	@echo "Running integration tests..."
	$(AGENT_PYTEST) tests/integration/ -v

test-security: agent-venv ## Run security tests (red team)
	@echo "Running security tests..."
	$(AGENT_PYTEST) tests/security/ -v

test-microsandbox: agent-venv ## Run MicroSandbox provider tests (set RUN_MICROSANDBOX_TESTS=1 for live integration)
	@echo "Running MicroSandbox executor/provider tests..."
	$(AGENT_PYTEST) tests/unit/test_microsandbox_executor.py tests/unit/test_executor_factory.py tests/unit/test_sandbox_provider_selection.py tests/integration/test_microsandbox_executor_integration.py -v

coverage: agent-venv ## Generate test coverage report
	$(AGENT_PYTEST) tests/ --cov=agent-server --cov-report=html --cov-report=term
	@echo "✓ Coverage report generated in htmlcov/index.html"

##@ Code Quality

lint: ## Run linters (ruff, black)
	@echo "Running linters..."
	cd agent-server && ruff check .
	cd agent-server && black --check .

format: ## Auto-format code
	@echo "Formatting code..."
	cd agent-server && black .
	cd agent-server && ruff check --fix .
	@echo "✓ Code formatted"

##@ Kubernetes

k8s-up: ## Create local Kubernetes cluster (kind)
	@echo "Creating local Kubernetes cluster..."
	kind create cluster --name csv-analyst
	@echo "✓ Cluster created"

k8s-down: ## Delete local Kubernetes cluster
	kind delete cluster --name csv-analyst

helm-install: ## Install application via Helm
	@echo "Installing CSV Analyst Chat via Helm..."
	helm install csv-analyst ./helm/csv-analyst-chat
	@echo "✓ Application installed"

helm-upgrade: ## Upgrade Helm release
	helm upgrade csv-analyst ./helm/csv-analyst-chat

helm-uninstall: ## Uninstall Helm release
	helm uninstall csv-analyst

k8s-smoke: ## Run smoke tests against K8s deployment
	@echo "Running K8s smoke tests..."
	@echo "TODO: Implement smoke tests"

##@ Docker

build-runner: ## Build runner Docker image
	docker build -t csv-analyst-runner:latest ./runner

build-runner-test: ## Build runner Docker image for integration tests
	docker build -t csv-analyst-runner:test ./runner

build-agent: ## Build agent-server Docker image
	docker build -t csv-analyst-agent:latest ./agent-server

build-ui: ## Build UI Docker image
	docker build -t csv-analyst-ui:latest ./ui

build-all: build-runner build-agent build-ui ## Build all Docker images

push: ## Push Docker images to registry
	@echo "TODO: Configure registry and push images"

##@ Datasets

validate-datasets: ## Validate dataset registry and files
	@echo "Validating datasets..."
	python scripts/validate_datasets.py
	@echo "✓ Datasets validated"

gen-dataset-hashes: ## Generate SHA256 hashes for datasets
	@echo "Generating dataset version hashes..."
	python scripts/hash_datasets.py

##@ Cleanup

clean: ## Clean build artifacts and caches
	@echo "Cleaning build artifacts..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf htmlcov/ .coverage
	@echo "✓ Cleaned"

clean-docker: ## Remove all project Docker containers and images
	docker compose down -v
	docker rmi csv-analyst-runner csv-analyst-agent csv-analyst-ui 2>/dev/null || true

##@ Release

release: ## Create a new release (usage: make release TAG=v1.0.0)
	@if [ -z "$(TAG)" ]; then \
		echo "Error: TAG not specified. Usage: make release TAG=v1.0.0"; \
		exit 1; \
	fi
	@echo "Creating release $(TAG)..."
	@echo "TODO: Build, tag, and push images with version $(TAG)"

##@ Database

db-migrate: ## Run database migrations (for run capsule storage)
	@echo "Running database migrations..."
	@echo "TODO: Implement migrations"

db-reset: ## Reset database (WARNING: destroys data)
	@echo "Resetting database..."
	@echo "TODO: Implement db reset"

##@ Documentation

docs-serve: ## Serve documentation locally
	@echo "Serving documentation..."
	@echo "TODO: Set up doc server (mkdocs or similar)"

docs-build: ## Build documentation
	@echo "Building documentation..."
	@echo "TODO: Build docs"

##@ Utilities

smoke: ## Quick smoke test (local Docker mode)
	@echo "Running quick smoke test..."
	@echo "TODO: Implement smoke test script"

shell-agent: ## Open shell in agent-server container
	docker compose exec agent-server /bin/bash

shell-runner: ## Open shell in runner container
	docker run -it --rm csv-analyst-runner:latest /bin/bash

logs-agent: ## View agent-server logs
	docker compose logs -f agent-server

logs-runner: ## View runner logs
	@echo "Runner logs are ephemeral (per-run containers)"

ps: ## Show running containers/pods
	@echo "Docker containers:"
	@docker compose ps
	@echo "\nKubernetes pods:"
	@kubectl get pods -l app=csv-analyst 2>/dev/null || echo "No K8s cluster detected"
