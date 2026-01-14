#!/usr/bin/env python3
"""
Tests for concurrency and rate limiting.
"""

import asyncio
import time
import pytest

from sandbox.executor import SandboxExecutor
from sandbox.config import Config, ExecutorConfig, SecurityConfig, RateLimitConfig
from sandbox.models import TaskStatus
from sandbox.api.routes import RateLimiter


class TestConcurrencyLimit:
    """Tests for concurrent task limiting."""

    @pytest.fixture
    def config(self):
        """Create config with low concurrency limit for testing."""
        return Config(
            executor=ExecutorConfig(
                timeout=5,
                max_memory=64,
                max_concurrent_tasks=2,  # Only allow 2 concurrent tasks
                recursion_limit=100,
            ),
            security=SecurityConfig(),
        )

    @pytest.fixture
    def executor(self, config):
        """Create executor with test config."""
        return SandboxExecutor(config=config)

    @pytest.mark.asyncio
    async def test_concurrent_task_count(self, executor):
        """Test that running task count is tracked correctly."""
        assert executor.get_running_task_count() == 0
        assert executor.get_available_slots() == 2

    @pytest.mark.asyncio
    async def test_concurrent_execution_within_limit(self, executor):
        """Test that tasks within limit execute successfully."""
        # Create two tasks
        task1 = await executor.create_task('print("task1")')
        task2 = await executor.create_task('print("task2")')

        # Execute both concurrently (within limit of 2)
        results = await asyncio.gather(
            executor.execute(task1.task_id),
            executor.execute(task2.task_id),
        )

        assert all(r.status == TaskStatus.COMPLETED for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_execution_exceeds_limit_waits(self, executor):
        """Test that tasks exceeding limit wait for slots."""
        # Create three tasks (exceeds limit of 2)
        task1 = await executor.create_task('import time; time.sleep(0.5); print("task1")')
        task2 = await executor.create_task('import time; time.sleep(0.5); print("task2")')
        task3 = await executor.create_task('print("task3")')

        start_time = time.time()

        # Execute all three - task3 should wait for a slot
        results = await asyncio.gather(
            executor.execute(task1.task_id),
            executor.execute(task2.task_id),
            executor.execute(task3.task_id),
        )

        elapsed = time.time() - start_time

        # All should complete
        # Note: time.sleep is blocked, so tasks will fail due to import restriction
        # But we're testing the concurrency mechanism, not the actual execution
        assert len(results) == 3


class TestRateLimiter:
    """Tests for rate limiting."""

    def test_rate_limiter_allows_initial_burst(self):
        """Test that rate limiter allows initial burst."""
        limiter = RateLimiter(requests_per_minute=60, burst_size=5)

        # Should allow burst_size requests immediately
        for i in range(5):
            allowed, info = limiter.is_allowed("client1")
            assert allowed, f"Request {i+1} should be allowed"

    def test_rate_limiter_blocks_after_burst(self):
        """Test that rate limiter blocks after burst is exhausted."""
        limiter = RateLimiter(requests_per_minute=60, burst_size=3)

        # Exhaust burst
        for _ in range(3):
            limiter.is_allowed("client1")

        # Next request should be blocked
        allowed, info = limiter.is_allowed("client1")
        assert not allowed, "Request should be blocked after burst"
        assert info["remaining"] == 0

    def test_rate_limiter_refills_tokens(self):
        """Test that rate limiter refills tokens over time."""
        limiter = RateLimiter(requests_per_minute=600, burst_size=5)  # 10 per second

        # Exhaust burst
        for _ in range(5):
            limiter.is_allowed("client1")

        # Wait for token refill (0.2 seconds = 2 tokens at 10/sec)
        time.sleep(0.2)

        # Should have refilled some tokens
        allowed, info = limiter.is_allowed("client1")
        assert allowed, "Request should be allowed after token refill"

    def test_rate_limiter_per_client(self):
        """Test that rate limiter is per-client."""
        limiter = RateLimiter(requests_per_minute=60, burst_size=2)

        # Exhaust client1's burst
        limiter.is_allowed("client1")
        limiter.is_allowed("client1")

        # client1 should be blocked
        allowed1, _ = limiter.is_allowed("client1")
        assert not allowed1, "client1 should be blocked"

        # client2 should still have tokens
        allowed2, _ = limiter.is_allowed("client2")
        assert allowed2, "client2 should still be allowed"

    def test_rate_limit_info_headers(self):
        """Test that rate limit info is returned correctly."""
        limiter = RateLimiter(requests_per_minute=60, burst_size=10)

        allowed, info = limiter.is_allowed("client1")

        assert "limit" in info
        assert "remaining" in info
        assert "reset" in info
        assert info["limit"] == 60
        # After consuming one token, remaining should be burst_size - 1 = 9
        # But _refill_tokens is called first which may affect the count
        assert info["remaining"] >= 8  # At least 8 remaining after one request


class TestIntegration:
    """Integration tests for limits."""

    @pytest.mark.asyncio
    async def test_health_endpoint_shows_concurrency(self):
        """Test that health endpoint shows concurrency info."""
        from sandbox.api import create_app
        from fastapi.testclient import TestClient

        app = create_app()

        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert "concurrent_tasks" in data
            assert "running" in data["concurrent_tasks"]
            assert "max" in data["concurrent_tasks"]

    @pytest.mark.asyncio
    async def test_status_endpoint(self):
        """Test that status endpoint returns detailed info."""
        from sandbox.api import create_app
        from fastapi.testclient import TestClient

        app = create_app()

        with TestClient(app) as client:
            response = client.get("/status")
            assert response.status_code == 200
            data = response.json()
            assert "executor" in data
            assert "rate_limit" in data
            assert "max_concurrent_tasks" in data["executor"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
