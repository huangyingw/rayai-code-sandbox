# Code Executor Sandbox - Makefile
# Quick start commands for development and testing

.PHONY: help setup build run test test-unit test-security clean

# Default target
help:
	@echo "Code Executor Sandbox - Available Commands"
	@echo ""
	@echo "  make setup         - Create venv and install dependencies"
	@echo "  make build         - Build Docker sandbox image"
	@echo "  make run           - Start the API server"
	@echo "  make test          - Run all tests"
	@echo "  make test-unit     - Run unit tests only"
	@echo "  make test-security - Run security tests"
	@echo "  make demo          - Run demo with test examples"
	@echo "  make clean         - Remove build artifacts"
	@echo ""
	@echo "Quick Start:"
	@echo "  make setup build run"
	@echo ""

# Setup virtual environment and install dependencies
setup:
	@echo "Creating virtual environment..."
	python3 -m venv venv
	@echo "Installing dependencies..."
	./venv/bin/pip install -r requirements.txt
	@echo ""
	@echo "Setup complete! Activate with: source venv/bin/activate"

# Build Docker sandbox image
build:
	@echo "Building Docker sandbox image..."
	docker build -t python-sandbox:latest -f Dockerfile.sandbox .
	@echo ""
	@echo "Docker image built successfully!"

# Run the API server
run:
	@echo "Starting Code Executor Sandbox API..."
	@echo "API docs: http://localhost:8000/docs"
	@echo ""
	./venv/bin/python main.py

# Run all tests (requires server running)
test: test-unit
	@echo "Running integration tests..."
	./venv/bin/python test_examples.py
	./venv/bin/python security_tests.py

# Run unit tests only
test-unit:
	@echo "Running unit tests..."
	./venv/bin/pytest tests/ -v

# Run security tests (requires server running)
test-security:
	@echo "Running security tests..."
	@echo "Make sure server is running: make run"
	./venv/bin/python security_tests.py

# Run demo examples (requires server running)
demo:
	@echo "Running demo examples..."
	@echo "Make sure server is running: make run"
	./venv/bin/python test_examples.py

# Clean build artifacts
clean:
	rm -rf venv
	rm -rf __pycache__
	rm -rf .pytest_cache
	rm -rf sandbox/__pycache__
	rm -rf sandbox/**/__pycache__
	rm -rf tests/__pycache__
	find . -name "*.pyc" -delete
	@echo "Cleaned!"
