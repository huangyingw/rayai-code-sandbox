"""
Pytest configuration and fixtures.
"""

import warnings


# Suppress asyncio subprocess cleanup warnings
def pytest_configure(config):
    """Suppress asyncio cleanup warnings globally."""
    warnings.filterwarnings(
        "ignore",
        message=".*Event loop is closed.*",
    )
    warnings.filterwarnings(
        "ignore",
        message=".*BaseSubprocessTransport.*",
    )
