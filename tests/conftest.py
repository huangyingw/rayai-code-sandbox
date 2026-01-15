"""
Pytest configuration and fixtures.
"""

import asyncio
import pytest
import warnings


# Suppress asyncio subprocess cleanup warnings
@pytest.fixture(autouse=True)
def suppress_asyncio_warnings():
    """Suppress asyncio event loop cleanup warnings."""
    warnings.filterwarnings(
        "ignore",
        message="Exception ignored in.*BaseSubprocessTransport",
        category=ResourceWarning
    )
    yield


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for session scope."""
    loop = asyncio.new_event_loop()
    yield loop
    # Give pending tasks time to clean up
    loop.run_until_complete(asyncio.sleep(0.1))
    loop.close()
