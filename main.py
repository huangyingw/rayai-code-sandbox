"""
Code Executor Sandbox API

A secure HTTP API for executing arbitrary Python code with real-time streaming output.

Security features:
- Docker container isolation (when available)
- Resource limits (CPU, memory, processes)
- Network isolation
- Restricted Python builtins
- Module whitelist

Entry point for the application.
"""

import shutil

import uvicorn

from sandbox.api import create_app
from sandbox.config import config
from sandbox.logging import setup_logging


# Set up logging
setup_logging()

# Determine if Docker is available
def is_docker_enabled() -> bool:
    """Check if Docker should be used based on config and availability."""
    use_docker_setting = config.security.use_docker.lower()

    if use_docker_setting == "true":
        return True
    elif use_docker_setting == "false":
        return False
    else:  # auto
        return shutil.which("docker") is not None


# Global Docker status
docker_enabled = is_docker_enabled()

# Create application
app = create_app()


@app.get("/info")
async def get_info():
    """Get sandbox configuration and security info."""
    return {
        "version": "1.1.0",
        "docker_enabled": docker_enabled,
        "security_features": {
            "container_isolation": docker_enabled,
            "network_isolation": docker_enabled,
            "resource_limits": True,
            "restricted_builtins": True,
            "module_whitelist": docker_enabled,
            "rate_limiting": config.rate_limit.enabled,
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
