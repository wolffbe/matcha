.PHONY: install db db-stop run dev test test-audio test-video test-image clean logs help reset-db stop dev-bg

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

# Run all tests (assumes app is already running)
test: test-audio test-video test-image

# Run audio matching tests
test-audio:
	pytest -v -s tests/api/audio/test_audio_matching.py

# Run audio matching tests and generate plots
test-audio-plot:
	pytest -v -s tests/api/audio/test_audio_matching.py 2>&1 | tee tests/api/audio/test_audio_matching.log
	python tests/api/audio/plot_audio_matching.py

# Run video matching tests
test-video:
	pytest -v -s tests/api/video/test_video_matching.py

# Run video matching tests and generate plots
test-video-plot:
	pytest -v -s tests/api/video/test_video_matching.py | tee tests/api/video/test_video_matching.log

# Run image matching tests
test-image:
	pytest -v -s tests/api/image/test_image_matching.py

# Run image matching tests and generate plots
test-image-plot:
	pytest -v -s tests/api/image/test_image_matching.py 2>&1 | tee tests/api/image/test_image_matching.log
	python tests/api/image/plot_image_matching.py

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
	@echo "  install         - Install Python dependencies"
	@echo "  db              - Start Qdrant database in Docker"
	@echo "  db-stop         - Stop Qdrant database"
	@echo "  run             - Start app locally (starts db first)"
	@echo "  dev             - Start app locally with auto-reload"
	@echo "  dev-bg          - Start app in background"
	@echo "  stop            - Stop background app"
	@echo "  test            - Run all tests (app must be running)"
	@echo "  test-audio      - Run audio matching tests"
	@echo "  test-audio-plot - Run audio tests and generate plots"
	@echo "  test-video      - Run video matching tests"
	@echo "  test-video-plot - Run video tests and generate plots"
	@echo "  test-image      - Run image matching tests"
	@echo "  test-image-plot - Run image tests and generate plots"
	@echo "  logs            - View database logs"
	@echo "  clean           - Stop app/db, remove tmp/, __pycache__, docker volumes"
	@echo "  reset-db        - Reset all database collections"
	@echo "  help            - Show this help"