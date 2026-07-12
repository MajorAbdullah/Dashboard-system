# Cogni Board — Makefile
# Canonical make targets wired to this project's stack.
#
# The app is a single FastAPI service that serves both the API and the
# static `frontend/` (dc-runtime) on one port. Postgres + Redis run as
# docker containers; there is no separate frontend dev server and no
# migration tool (tables are auto-created by init_db() on boot).
# Production runs on Railway (see railway.json / Procfile), not docker
# compose, so there is no `production` lifecycle section here.
#
# Files referenced:
#   docker-compose.yml   (Postgres + Redis dev infra)

SHELL       := /bin/bash
COMPOSE     := docker compose
DEV_FILE    := docker-compose.yml
DEV         := $(COMPOSE) -f $(DEV_FILE)
ENV_FILE    := backend/.env
ENV_EXAMPLE := backend/.env.example
VENV        := backend/.venv
PYTHON      := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
UVICORN     := $(VENV)/bin/uvicorn
APP_PORT    := 8000
APP_URL     := http://localhost:$(APP_PORT)/Agentic%20Auth.dc.html

.DEFAULT_GOAL := help

# ─── Help ──────────────────────────────────────────────────────────────────────
.PHONY: help
help: ## Show this help
	@echo "Cogni Board — available make targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ─── Lifecycle (development) ───────────────────────────────────────────────────
.PHONY: start stop restart status logs dev
start: env-check ## Start Postgres+Redis containers, then run the app (API + UI) on :8000
	$(DEV) up -d --wait
	@echo ""
	@echo "Containers up. Starting app → $(APP_URL)"
	@echo "(Containers stay running after Ctrl+C — use \`make stop\` to halt them.)"
	@echo ""
	$(UVICORN) main:app --app-dir backend --reload --reload-dir backend --port $(APP_PORT)

stop: ## Halt dev containers (state is kept — resume with `make start`)
	$(DEV) stop

restart: ## Restart dev containers
	$(DEV) restart

status: ## Show status of dev containers
	$(DEV) ps

logs: ## Tail container logs (Ctrl+C to exit)
	$(DEV) logs -f --tail=200

dev: ## Run only the app server (assumes containers are already up)
	$(UVICORN) main:app --app-dir backend --reload --reload-dir backend --port $(APP_PORT)

# ─── Install ───────────────────────────────────────────────────────────────────
.PHONY: install install-all install-deps install-images
install: install-all ## Alias for `install-all`

install-all: env-check install-deps install-images ## Full setup: env, python deps, docker images
	@echo ""
	@echo "Install complete. Next: \`make start\` → $(APP_URL)"

install-deps: ## Create the venv (if needed) and install Python dependencies
	@if [ ! -d $(VENV) ]; then python3 -m venv $(VENV); fi
	$(PIP) install -r requirements.txt

install-images: ## Pull the Postgres/Redis images
	$(DEV) pull

# ─── Environment ───────────────────────────────────────────────────────────────
.PHONY: env-check env-init
env-check: ## Verify backend/.env exists (warn-only)
	@if [ ! -f $(ENV_FILE) ]; then \
		echo "WARNING: $(ENV_FILE) not found. Run \`make env-init\` to scaffold from $(ENV_EXAMPLE)."; \
	fi

env-init: ## Create backend/.env from backend/.env.example if missing
	@if [ -f $(ENV_FILE) ]; then \
		echo "$(ENV_FILE) already exists — leaving untouched."; \
	else \
		cp $(ENV_EXAMPLE) $(ENV_FILE) && echo "Created $(ENV_FILE) — fill in real values (OPENROUTER_API_KEY etc.)."; \
	fi

# ─── Database / shells ──────────────────────────────────────────────────────────
.PHONY: psql redis-cli sh-db db-backup
psql: ## Open psql in the running Postgres container
	$(DEV) exec postgres psql -U postgres -d ada

redis-cli: ## Open redis-cli in the running Redis container
	$(DEV) exec redis redis-cli

sh-db: ## Open a shell in the running Postgres container
	$(DEV) exec postgres sh

db-backup: ## Backup the Postgres database to a timestamped SQL file
	@mkdir -p backups
	$(DEV) exec -T postgres pg_dump -U postgres ada > backups/ada_$$(date +%Y%m%d_%H%M%S).sql
	@echo "Backup written to backups/"

# ─── Cleanup ───────────────────────────────────────────────────────────────────
.PHONY: clean clean-volumes nuke
clean: ## Stop containers and remove them (keeps volumes)
	-$(DEV) down

clean-volumes: ## Remove containers AND delete the Postgres volume (DESTRUCTIVE)
	@read -p "This will DELETE the Postgres volume (all local data). Continue? [y/N] " ans; \
	if [ "$$ans" = "y" ] || [ "$$ans" = "Y" ]; then \
		$(DEV) down -v; \
	else \
		echo "Aborted."; \
	fi

nuke: ## Containers + volumes + dangling images (DESTRUCTIVE)
	@read -p "Full reset: containers + volumes + dangling images. Continue? [y/N] " ans; \
	if [ "$$ans" = "y" ] || [ "$$ans" = "Y" ]; then \
		$(DEV) down -v --rmi local; \
		docker image prune -f; \
	else \
		echo "Aborted."; \
	fi
