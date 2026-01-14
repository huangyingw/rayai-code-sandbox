"""
Code Executor Sandbox API

Entry point for the application.
"""

import uvicorn

from sandbox.api import create_app
from sandbox.config import config
from sandbox.logging import setup_logging


# Set up logging
setup_logging()

# Create application
app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
    )
