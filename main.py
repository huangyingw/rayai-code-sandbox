"""
Code Executor Sandbox API

A secure HTTP API for executing arbitrary Python code with real-time streaming output.

Security features:
- Docker container isolation (MANDATORY)
- Resource limits (CPU, memory, processes)
- Network isolation
- Restricted Python builtins
- Module whitelist

Entry point for the application.
"""

import shutil
import sys

import uvicorn

from sandbox.api import create_app
from sandbox.config import config
from sandbox.logging import setup_logging


# Set up logging
setup_logging()


def check_docker_available() -> bool:
    """Check if Docker is available on the system."""
    return shutil.which("docker") is not None


def verify_docker_requirement():
    """Verify Docker is available. Exit if not."""
    if not check_docker_available():
        print("ERROR: Docker is required but not found.", file=sys.stderr)
        print("Please install Docker to run this application.", file=sys.stderr)
        print("See: https://docs.docker.com/get-docker/", file=sys.stderr)
        sys.exit(1)


# Verify Docker is available at startup
verify_docker_requirement()

# Create application
app = create_app()


@app.get("/info")
async def get_info():
    """Get sandbox configuration and security info."""
    return {
        "version": "2.0.0",
        "docker_required": True,
        "security_features": {
            "container_isolation": True,
            "network_isolation": True,
            "resource_limits": True,
            "restricted_builtins": True,
            "module_whitelist": True,
            "rate_limiting": config.rate_limit.enabled,
        },
        "docker_config": {
            "image": config.docker.image,
            "memory_limit": config.docker.memory_limit,
            "cpu_limit": config.docker.cpu_limit,
            "pids_limit": config.docker.pids_limit,
            "network": config.docker.network,
            "read_only": config.docker.read_only,
        },
        "limits": {
            "timeout_seconds": config.executor.timeout,
            "max_memory_mb": config.executor.max_memory,
            "max_output_bytes": config.executor.max_output_size,
            "max_concurrent_tasks": config.executor.max_concurrent_tasks,
        },
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
    )
