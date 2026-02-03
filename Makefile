# CSV Analyst Chat - Makefile
# Common development tasks

.PHONY: help dev test clean install build-runner-test test-runner test-agent-server run-agent run-agent-dev run-mlflow agent-venv local-preflight local-deploy local-smoke deploy-all-local k8s-preflight k8s-load-images k8s-create-llm-secret k8s-deploy-k8s-job k8s-deploy-microsandbox k8s-test-runs helm-lint helm-template helm-template-k8s-job helm-template-microsandbox helm-install-k8s-job helm-install-microsandbox build-agent-k8s build-runner-k8s kind-load-agent-image

# Default target
.DEFAULT_GOAL := help

AGENT_VENV := agent-server/.venv
AGENT_PYTHON := $(AGENT_VENV)/bin/python
AGENT_PIP := $(AGENT_VENV)/bin/pip
AGENT_PYTEST := $(AGENT_VENV)/bin/pytest
AGENT_UVICORN := $(AGENT_VENV)/bin/uvicorn
AGENT_MLFLOW := $(AGENT_VENV)/bin/mlflow
AGENT_VENV_STAMP := $(AGENT_VENV)/.deps.stamp

KIND_CLUSTER_NAME ?= csv-analyst
K8S_NAMESPACE ?= csv-analyst
HELM_RELEASE ?= csv-analyst
HELM_CHART ?= ./helm/csv-analyst-chat
K8S_IMAGE_REPOSITORY ?= csv-analyst-agent
K8S_IMAGE_TAG ?= dev
K8S_SANDBOX_PROVIDER ?= k8s
K8S_RUNNER_IMAGE ?= csv-analyst-runner:$(K8S_IMAGE_TAG)
LLM_SECRET_NAME ?= csv-analyst-llm
MSB_SERVER_URL ?=
MSB_API_KEY ?=
HELM_VALUES_FILE ?=
HELM_EXTRA_SET ?=

##@ General

help: ## Display this help message
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

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

run-mlflow: agent-venv ## Run local MLflow tracking server (http://localhost:5000)
	PATH="$(abspath $(AGENT_VENV))/bin:$$PATH" $(AGENT_MLFLOW) server --host 0.0.0.0 --port 5000 --backend-store-uri sqlite:///mlflow.db --default-artifact-root ./mlruns

local-preflight: ## Check local (non-K8s) prerequisites
	@command -v python3 >/dev/null || (echo "ERROR: python3 is required."; exit 1)
	@command -v docker >/dev/null || (echo "ERROR: docker is required."; exit 1)
	@echo "✓ Local prerequisites look good"

local-deploy: local-preflight agent-venv build-runner-test ## Set up local development mode (FastAPI + Docker runner)
	@echo ""
	@echo "Local setup complete."
	@echo "Next:"
	@echo "  1) cp .env.example .env"
	@echo "  2) export OPENAI_API_KEY=...   (or set in .env)"
	@echo "  3) make run-agent-dev"
	@echo "  4) open http://localhost:8000"

local-smoke: ## Smoke-check local server (expects make run-agent-dev already running)
	@curl -sf http://127.0.0.1:8000/healthz >/dev/null || (echo "ERROR: /healthz failed. Is server running?"; exit 1)
	@curl -sf http://127.0.0.1:8000/datasets >/dev/null || (echo "ERROR: /datasets failed."; exit 1)
	@echo "✓ Local smoke checks passed"

deploy-all-local: ## One-command full local setup: local deps + kind deploy (k8s-job) + functional /runs check
	@if [ -z "$$OPENAI_API_KEY" ]; then \
		echo "ERROR: OPENAI_API_KEY is not set."; \
		echo "Set it with: export OPENAI_API_KEY=..."; \
		exit 1; \
	fi
	$(MAKE) local-deploy
	$(MAKE) k8s-deploy-k8s-job \
		K8S_NAMESPACE=$(K8S_NAMESPACE) \
		HELM_RELEASE=$(HELM_RELEASE) \
		K8S_IMAGE_REPOSITORY=$(K8S_IMAGE_REPOSITORY) \
		K8S_IMAGE_TAG=$(K8S_IMAGE_TAG) \
		K8S_RUNNER_IMAGE=$(K8S_RUNNER_IMAGE) \
		LLM_SECRET_NAME=$(LLM_SECRET_NAME)
	$(MAKE) k8s-test-runs K8S_NAMESPACE=$(K8S_NAMESPACE) HELM_RELEASE=$(HELM_RELEASE)
	@echo "✓ Full local setup + K8s functional check completed"

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

k8s-preflight: ## Check Kubernetes deployment prerequisites
	@command -v docker >/dev/null || (echo "ERROR: docker is required."; exit 1)
	@command -v kind >/dev/null || (echo "ERROR: kind is required."; exit 1)
	@command -v kubectl >/dev/null || (echo "ERROR: kubectl is required."; exit 1)
	@command -v helm >/dev/null || (echo "ERROR: helm is required."; exit 1)
	@command -v curl >/dev/null || (echo "ERROR: curl is required."; exit 1)
	@echo "✓ Kubernetes prerequisites look good"

k8s-up: ## Create local Kubernetes cluster (kind)
	@echo "Creating local Kubernetes cluster..."
	kind create cluster --name $(KIND_CLUSTER_NAME) || true
	@echo "✓ Cluster created"

k8s-down: ## Delete local Kubernetes cluster
	kind delete cluster --name $(KIND_CLUSTER_NAME)

helm-lint: ## Lint Helm chart
	helm lint $(HELM_CHART)

helm-template: ## Render Helm chart to stdout for inspection
	helm template $(HELM_RELEASE) $(HELM_CHART) \
		--namespace $(K8S_NAMESPACE) \
		--set image.repository=$(K8S_IMAGE_REPOSITORY) \
		--set image.tag=$(K8S_IMAGE_TAG) \
		--set env.SANDBOX_PROVIDER=$(K8S_SANDBOX_PROVIDER) \
		$(if $(HELM_VALUES_FILE),-f $(HELM_VALUES_FILE),) \
		$(HELM_EXTRA_SET)

helm-template-k8s-job: ## Render Helm chart with native k8s-job profile
	$(MAKE) helm-template \
		HELM_VALUES_FILE=./helm/csv-analyst-chat/profiles/values-k8s-job.yaml \
		K8S_SANDBOX_PROVIDER=k8s

helm-template-microsandbox: ## Render Helm chart with microsandbox profile
	$(MAKE) helm-template \
		HELM_VALUES_FILE=./helm/csv-analyst-chat/profiles/values-microsandbox.yaml \
		K8S_SANDBOX_PROVIDER=microsandbox

helm-install: ## Install application via Helm
	@echo "Installing CSV Analyst Chat via Helm in namespace $(K8S_NAMESPACE)..."
	kubectl create namespace $(K8S_NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install $(HELM_RELEASE) $(HELM_CHART) \
		--namespace $(K8S_NAMESPACE) \
		--set image.repository=$(K8S_IMAGE_REPOSITORY) \
		--set image.tag=$(K8S_IMAGE_TAG) \
		--set env.SANDBOX_PROVIDER=$(K8S_SANDBOX_PROVIDER) \
		$(if $(HELM_VALUES_FILE),-f $(HELM_VALUES_FILE),) \
		$(HELM_EXTRA_SET)
	@echo "✓ Application installed"

helm-install-k8s-job: ## Install Helm release with native k8s-job profile
	$(MAKE) helm-install \
		HELM_VALUES_FILE=./helm/csv-analyst-chat/profiles/values-k8s-job.yaml \
		K8S_SANDBOX_PROVIDER=k8s

helm-install-microsandbox: ## Install Helm release with microsandbox profile
	$(MAKE) helm-install \
		HELM_VALUES_FILE=./helm/csv-analyst-chat/profiles/values-microsandbox.yaml \
		K8S_SANDBOX_PROVIDER=microsandbox

helm-upgrade: ## Upgrade Helm release
	helm upgrade $(HELM_RELEASE) $(HELM_CHART) \
		--namespace $(K8S_NAMESPACE) \
		--set image.repository=$(K8S_IMAGE_REPOSITORY) \
		--set image.tag=$(K8S_IMAGE_TAG) \
		--set env.SANDBOX_PROVIDER=$(K8S_SANDBOX_PROVIDER) \
		$(if $(HELM_VALUES_FILE),-f $(HELM_VALUES_FILE),) \
		$(HELM_EXTRA_SET)

helm-uninstall: ## Uninstall Helm release
	helm uninstall $(HELM_RELEASE) --namespace $(K8S_NAMESPACE)

k8s-smoke: ## Run smoke tests against K8s deployment
	@echo "Running K8s smoke tests..."
	kubectl -n $(K8S_NAMESPACE) rollout status deploy -l app.kubernetes.io/instance=$(HELM_RELEASE)
	@SERVICE=$$(kubectl -n $(K8S_NAMESPACE) get svc -l app.kubernetes.io/instance=$(HELM_RELEASE) -o jsonpath='{.items[0].metadata.name}'); \
		echo "Using service $$SERVICE"; \
		kubectl -n $(K8S_NAMESPACE) port-forward svc/$$SERVICE 18000:8000 >/tmp/csv_analyst_k8s_pf.log 2>&1 & \
		PF_PID=$$!; \
		trap 'kill $$PF_PID >/dev/null 2>&1 || true' EXIT; \
		sleep 3; \
		curl -sf http://127.0.0.1:18000/healthz >/dev/null; \
		curl -sf http://127.0.0.1:18000/datasets >/dev/null; \
		echo "✓ K8s smoke checks passed"

##@ Docker

build-runner: ## Build runner Docker image
	docker build -t csv-analyst-runner:latest ./runner

build-runner-k8s: ## Build runner image with baked datasets for Kubernetes
	docker build -f runner/Dockerfile.k8s -t csv-analyst-runner:$(K8S_IMAGE_TAG) .

build-runner-test: ## Build runner Docker image for integration tests
	docker build -t csv-analyst-runner:test ./runner

build-agent: ## Build agent-server Docker image
	docker build -t csv-analyst-agent:latest ./agent-server

build-agent-k8s: ## Build agent-server image with baked datasets for Kubernetes
	docker build -f agent-server/Dockerfile.k8s -t $(K8S_IMAGE_REPOSITORY):$(K8S_IMAGE_TAG) .

kind-load-agent-image: ## Load locally built agent image into kind
	kind load docker-image $(K8S_IMAGE_REPOSITORY):$(K8S_IMAGE_TAG) --name $(KIND_CLUSTER_NAME)

k8s-load-images: ## Load agent + runner images into kind
	kind load docker-image $(K8S_IMAGE_REPOSITORY):$(K8S_IMAGE_TAG) --name $(KIND_CLUSTER_NAME)
	kind load docker-image $(K8S_RUNNER_IMAGE) --name $(KIND_CLUSTER_NAME)
	@echo "✓ Images loaded into kind"

k8s-create-llm-secret: ## Create/update LLM secret in K8s namespace (requires OPENAI_API_KEY env var)
	@if [ -z "$$OPENAI_API_KEY" ]; then \
		echo "ERROR: OPENAI_API_KEY is not set."; \
		echo "Set it with: export OPENAI_API_KEY=..."; \
		exit 1; \
	fi
	kubectl create namespace $(K8S_NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n $(K8S_NAMESPACE) create secret generic $(LLM_SECRET_NAME) \
		--from-literal=OPENAI_API_KEY="$$OPENAI_API_KEY" \
		--dry-run=client -o yaml | kubectl apply -f -
	@echo "✓ Secret $(LLM_SECRET_NAME) is ready in namespace $(K8S_NAMESPACE)"

k8s-deploy-k8s-job: k8s-preflight k8s-up build-runner-k8s build-agent-k8s k8s-load-images k8s-create-llm-secret ## One-command local K8s deploy using native k8s-job executor
	$(MAKE) helm-install-k8s-job \
		K8S_NAMESPACE=$(K8S_NAMESPACE) \
		HELM_RELEASE=$(HELM_RELEASE) \
		K8S_IMAGE_REPOSITORY=$(K8S_IMAGE_REPOSITORY) \
		K8S_IMAGE_TAG=$(K8S_IMAGE_TAG) \
		HELM_EXTRA_SET="--set image.pullPolicy=Never --set existingSecretName=$(LLM_SECRET_NAME) --set env.LLM_PROVIDER=openai --set env.RUNNER_IMAGE=$(K8S_RUNNER_IMAGE) --set env.K8S_NAMESPACE=$(K8S_NAMESPACE)"
	$(MAKE) k8s-smoke K8S_NAMESPACE=$(K8S_NAMESPACE) HELM_RELEASE=$(HELM_RELEASE)
	@echo "✓ K8s deploy (k8s-job mode) complete"

k8s-deploy-microsandbox: k8s-preflight k8s-up build-runner-k8s build-agent-k8s k8s-load-images k8s-create-llm-secret ## One-command local K8s deploy using microsandbox executor
	@if [ -z "$(MSB_SERVER_URL)" ]; then \
		echo "ERROR: MSB_SERVER_URL is required for microsandbox mode."; \
		echo "Example: make $@ MSB_SERVER_URL=http://microsandbox.default.svc.cluster.local:5555/api/v1/rpc"; \
		exit 1; \
	fi
	$(MAKE) helm-install-microsandbox \
		K8S_NAMESPACE=$(K8S_NAMESPACE) \
		HELM_RELEASE=$(HELM_RELEASE) \
		K8S_IMAGE_REPOSITORY=$(K8S_IMAGE_REPOSITORY) \
		K8S_IMAGE_TAG=$(K8S_IMAGE_TAG) \
		HELM_EXTRA_SET="--set image.pullPolicy=Never --set existingSecretName=$(LLM_SECRET_NAME) --set env.LLM_PROVIDER=openai --set env.MSB_SERVER_URL=$(MSB_SERVER_URL) --set env.MSB_API_KEY=$(MSB_API_KEY)"
	$(MAKE) k8s-smoke K8S_NAMESPACE=$(K8S_NAMESPACE) HELM_RELEASE=$(HELM_RELEASE)
	@echo "✓ K8s deploy (microsandbox mode) complete"
	@echo "NOTE: /runs will fail until MSB_SERVER_URL is reachable from the cluster."

k8s-test-runs: ## Functional /runs SQL check against a deployed release
	@SERVICE=$$(kubectl -n $(K8S_NAMESPACE) get svc -l app.kubernetes.io/instance=$(HELM_RELEASE) -o jsonpath='{.items[0].metadata.name}'); \
		echo "Using service $$SERVICE"; \
		kubectl -n $(K8S_NAMESPACE) port-forward svc/$$SERVICE 18000:8000 >/tmp/csv_analyst_k8s_pf.log 2>&1 & \
		PF_PID=$$!; \
		trap 'kill $$PF_PID >/dev/null 2>&1 || true' EXIT; \
		sleep 3; \
		curl -sS -X POST http://127.0.0.1:18000/runs \
			-H "Content-Type: application/json" \
			--data-binary '{"dataset_id":"support","query_type":"sql","sql":"SELECT COUNT(*) AS ticket_count FROM tickets"}'; \
		echo ""

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
