"""
Pytest configuration and fixtures.
"""

import asyncio
import gc
import warnings

import pytest


def pytest_configure(config):
    """Suppress asyncio cleanup warnings globally."""
    warnings.filterwarnings("ignore", message=".*Event loop is closed.*")
    warnings.filterwarnings("ignore", message=".*BaseSubprocessTransport.*")


@pytest.fixture(autouse=True)
async def cleanup_subprocesses():
    """Clean up any pending subprocesses after each test."""
    yield
    # Give pending callbacks time to run
    await asyncio.sleep(0.1)
    # Force garbage collection to clean up subprocess transports
    # before the event loop closes
    gc.collect()
    await asyncio.sleep(0.05)
