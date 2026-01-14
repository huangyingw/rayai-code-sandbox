# Code Executor Sandbox - Makefile

.PHONY: help setup build run test test-unit test-security clean check-docker

# Default target
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "  setup    Create venv and install dependencies"
	@echo "  build    Build Docker sandbox image"
	@echo "  run      Start the API server"
	@echo "  test     Run all tests"
	@echo "  clean    Remove build artifacts"
	@echo ""
	@echo "Quick Start: make setup build run"

# Check Docker accessibility
check-docker:
	@docker info > /dev/null 2>&1 || (echo "Error: Cannot connect to Docker." && \
		echo "Please ensure Docker is running and you have permission." && \
		echo "Try: sudo usermod -aG docker $$USER && newgrp docker" && exit 1)

# Setup virtual environment and install dependencies
setup:
	@python3 -m venv venv
	@./venv/bin/pip install -q -r requirements.txt
	@echo "Setup complete."

# Build Docker sandbox image
build: check-docker
	@echo "Building Docker image..."
	@docker build -q -t python-sandbox:latest -f Dockerfile.sandbox . > /dev/null
	@echo "Docker image ready."

# Run the API server
run: check-docker
	@echo "Starting server at http://localhost:8000"
	@echo "API docs: http://localhost:8000/docs"
	@./venv/bin/python main.py

# Run unit tests
test-unit:
	@./venv/bin/pytest tests/ -v

# Run security tests (requires server)
test-security:
	@./venv/bin/python security_tests.py

# Run all tests
test: test-unit

# Demo (requires server running)
demo:
	@./venv/bin/python test_examples.py

# Clean
clean:
	@rm -rf venv __pycache__ .pytest_cache
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned."
