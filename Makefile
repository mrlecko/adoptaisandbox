# CSV Analyst Chat - Makefile
# Common development tasks

.PHONY: help dev test clean install

# Default target
.DEFAULT_GOAL := help

##@ General

help: ## Display this help message
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Development

install: ## Install dependencies (agent-server and UI)
	@echo "Installing agent-server dependencies..."
	cd agent-server && python -m venv .venv && .venv/bin/pip install -r requirements.txt
	@echo "Installing UI dependencies..."
	cd ui && npm install
	@echo "✓ Dependencies installed"

dev: ## Start local development environment (docker-compose)
	@echo "Starting local development environment..."
	docker compose up --build
	@echo "✓ Services running at http://localhost:3000"

dev-down: ## Stop local development environment
	docker compose down

dev-logs: ## View logs from development environment
	docker compose logs -f

##@ Testing

test: ## Run all tests
	@echo "Running all tests..."
	pytest tests/ -v
	@echo "✓ All tests passed"

test-unit: ## Run unit tests only
	@echo "Running unit tests..."
	pytest tests/unit/ -v

test-integration: ## Run integration tests only
	@echo "Running integration tests..."
	pytest tests/integration/ -v

test-security: ## Run security tests (red team)
	@echo "Running security tests..."
	pytest tests/security/ -v

coverage: ## Generate test coverage report
	pytest tests/ --cov=agent-server --cov-report=html --cov-report=term
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
