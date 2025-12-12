.PHONY: install db db-stop run dev test clean logs help reset-db stop dev-bg

# Load and export all variables from .env file if it exists
ifneq (,$(wildcard ./.env))
    include .env
    export $(shell sed 's/=.*//' .env)
endif

# Python settings
PYTHON ?= python
PIP ?= pip
HOST ?= 0.0.0.0
PORT ?= 8000

# Paths
APP_DIR = matching
APP_MODULE = app.routes:app

# Default to localhost for local development
QDRANT_HOST ?= localhost

# Install dependencies
install:
	$(PYTHON) -m $(PIP) install -r $(APP_DIR)/requirements.txt

# Start only the database (Qdrant) in Docker
db:
	docker-compose up -d qdrant
	@echo "Waiting for Qdrant to be ready..."
	@timeout 30 sh -c 'until curl -s http://localhost:6333/collections > /dev/null 2>&1; do sleep 1; done' || (echo "Qdrant failed to start"; exit 1)
	@echo "Qdrant is ready"

# Stop the database
db-stop:
	docker-compose stop qdrant

# Run the app locally
run: db
	cd $(APP_DIR) && PYTHONPATH=. QDRANT_HOST=$(QDRANT_HOST) $(PYTHON) -m uvicorn $(APP_MODULE) --host $(HOST) --port $(PORT)

# Run the app locally with auto-reload
dev: db
	cd $(APP_DIR) && PYTHONPATH=. QDRANT_HOST=$(QDRANT_HOST) $(PYTHON) -m uvicorn $(APP_MODULE) --host $(HOST) --port $(PORT) --reload --no-access-log

# Run tests (assumes app is already running)
test:
	pytest -v

# Start app in background for testing
dev-bg: db
	cd $(APP_DIR) && PYTHONPATH=. QDRANT_HOST=$(QDRANT_HOST) $(PYTHON) -m uvicorn $(APP_MODULE) --host $(HOST) --port $(PORT) &
	@echo $$! > .app.pid
	@sleep 2
	@echo "App started with PID $$(cat .app.pid)"

# Stop background app
stop:
	@if [ -f .app.pid ]; then \
		kill $$(cat .app.pid) 2>/dev/null || true; \
		rm -f .app.pid; \
		echo "App stopped"; \
	fi

# View database logs
logs:
	docker-compose logs -f qdrant

# Clean up
clean: stop db-stop
	docker-compose down -v
	rm -rf ./tmp
	rm -f .app.pid
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Reset database
reset-db: db
	curl -X DELETE http://localhost:6333/collections/video_hashes 2>/dev/null || true
	curl -X DELETE http://localhost:6333/collections/audio_hashes 2>/dev/null || true
	curl -X DELETE http://localhost:6333/collections/image_hashes 2>/dev/null || true
	@echo "Database reset"

# Show help
help:
	@echo "Available targets:"
	@echo "  install    - Install Python dependencies"
	@echo "  db         - Start Qdrant database in Docker"
	@echo "  db-stop    - Stop Qdrant database"
	@echo "  run        - Start app locally (starts db first)"
	@echo "  dev        - Start app locally with auto-reload"
	@echo "  test       - Run tests (app must be running)"
	@echo "  logs       - View database logs"
	@echo "  clean      - Stop everything and clean up"
	@echo "  reset-db   - Reset all database collections"
	@echo "  help       - Show this help"