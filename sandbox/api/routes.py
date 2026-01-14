"""
FastAPI routes for the code executor API.
"""

import asyncio
import logging
import time
from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import config
from ..models import TaskStatus
from ..executor import SandboxExecutor


logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple in-memory rate limiter using token bucket algorithm."""

    def __init__(self, requests_per_minute: int = 60, burst_size: int = 10):
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self.tokens: dict[str, float] = defaultdict(lambda: float(burst_size))
        self.last_update: dict[str, float] = defaultdict(time.time)
        # Rate at which tokens are added (tokens per second)
        self.rate = requests_per_minute / 60.0

    def _refill_tokens(self, client_id: str) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_update[client_id]
        self.last_update[client_id] = now

        # Add tokens based on elapsed time
        self.tokens[client_id] = min(
            self.burst_size,
            self.tokens[client_id] + elapsed * self.rate
        )

    def is_allowed(self, client_id: str) -> tuple[bool, dict]:
        """Check if request is allowed and consume a token if so.

        Returns:
            (is_allowed, rate_limit_info)
        """
        self._refill_tokens(client_id)

        info = {
            "limit": self.requests_per_minute,
            "remaining": int(self.tokens[client_id]),
            "reset": int(self.burst_size / self.rate),
        }

        if self.tokens[client_id] >= 1:
            self.tokens[client_id] -= 1
            info["remaining"] = int(self.tokens[client_id])
            return True, info
        else:
            return False, info


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce rate limiting on API requests."""

    def __init__(self, app, rate_limiter: RateLimiter, enabled: bool = True):
        super().__init__(app)
        self.rate_limiter = rate_limiter
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting if disabled or for health check
        if not self.enabled or request.url.path == "/health":
            return await call_next(request)

        # Get client identifier (IP address)
        client_id = request.client.host if request.client else "unknown"

        # Check rate limit
        is_allowed, info = self.rate_limiter.is_allowed(client_id)

        if not is_allowed:
            logger.warning(f"Rate limit exceeded for client {client_id}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down.",
                    "retry_after": info["reset"],
                },
                headers={
                    "X-RateLimit-Limit": str(info["limit"]),
                    "X-RateLimit-Remaining": str(info["remaining"]),
                    "X-RateLimit-Reset": str(info["reset"]),
                    "Retry-After": str(info["reset"]),
                }
            )

        # Process request and add rate limit headers to response
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
        response.headers["X-RateLimit-Reset"] = str(info["reset"])
        return response


# Request/Response models
class ExecuteRequest(BaseModel):
    """Request body for code execution."""
    code: str = Field(
        ...,
        description="Python code to execute",
        min_length=1,
        max_length=100000
    )


class ExecuteResponse(BaseModel):
    """Response for code execution request."""
    task_id: str


class TaskResponse(BaseModel):
    """Response for task status query."""
    task_id: str
    status: TaskStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    error_message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


def create_app(executor: Optional[SandboxExecutor] = None) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        executor: Optional executor instance. Creates default if not provided.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="Code Executor Sandbox",
        description="Execute Python code safely with streaming output",
        version="1.0.0",
    )

    # Add rate limiting middleware
    rate_limiter = RateLimiter(
        requests_per_minute=config.rate_limit.requests_per_minute,
        burst_size=config.rate_limit.burst_size,
    )
    app.add_middleware(
        RateLimitMiddleware,
        rate_limiter=rate_limiter,
        enabled=config.rate_limit.enabled,
    )

    # Use provided executor or create default
    _executor = executor or SandboxExecutor()

    @app.post("/execute", response_model=ExecuteResponse)
    async def execute_code(request: ExecuteRequest, background_tasks: BackgroundTasks):
        """
        Submit Python code for execution.

        Returns a task_id that can be used to track execution status and stream output.
        """
        task = await _executor.create_task(request.code)
        background_tasks.add_task(_executor.execute, task.task_id)
        return ExecuteResponse(task_id=task.task_id)

    @app.get("/tasks/{task_id}", response_model=TaskResponse)
    async def get_task(task_id: str):
        """Get the status and result of a task."""
        task = await _executor.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        return TaskResponse(
            task_id=task.task_id,
            status=task.status,
            stdout=task.stdout,
            stderr=task.stderr,
            exit_code=task.exit_code,
            error_message=task.error_message,
            created_at=task.created_at.isoformat(),
            started_at=task.started_at.isoformat() if task.started_at else None,
            finished_at=task.finished_at.isoformat() if task.finished_at else None,
        )

    @app.get("/tasks/{task_id}/stream")
    async def stream_task_output(task_id: str):
        """
        Stream the output of a running task in real-time.

        Returns a Server-Sent Events (SSE) stream.
        """
        task = await _executor.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        async def event_generator():
            """Generate SSE events for task output."""
            last_index = 0

            while True:
                current_task = await _executor.get_task(task_id)
                if not current_task:
                    break

                # Get new output lines
                buffer = _executor.get_output_buffer(task_id)
                while last_index < len(buffer):
                    line = buffer[last_index]
                    yield f"data: {line}\n\n"
                    last_index += 1

                # Check if task is done
                if current_task.status in (
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.TIMEOUT,
                    TaskStatus.KILLED,
                ):
                    yield f"event: status\ndata: {current_task.status.value}\n\n"
                    if current_task.error_message:
                        yield f"event: error\ndata: {current_task.error_message}\n\n"
                    yield "event: done\ndata: finished\n\n"
                    break

                await asyncio.sleep(0.1)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.delete("/tasks/{task_id}")
    async def kill_task(task_id: str):
        """Kill a running task."""
        task = await _executor.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        if task.status != TaskStatus.RUNNING:
            raise HTTPException(
                status_code=400,
                detail=f"Task {task_id} is not running (status: {task.status})"
            )

        killed = await _executor.kill_task(task_id)
        if killed:
            return {"message": f"Task {task_id} killed successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to kill task")

    @app.get("/health")
    async def health_check():
        """Health check endpoint with system status."""
        return {
            "status": "healthy",
            "concurrent_tasks": {
                "running": _executor.get_running_task_count(),
                "max": config.executor.max_concurrent_tasks,
                "available": config.executor.max_concurrent_tasks - _executor.get_running_task_count(),
            },
            "rate_limit": {
                "enabled": config.rate_limit.enabled,
                "requests_per_minute": config.rate_limit.requests_per_minute,
            }
        }

    @app.get("/status")
    async def system_status():
        """Detailed system status endpoint."""
        return {
            "executor": {
                "running_tasks": _executor.get_running_task_count(),
                "max_concurrent_tasks": config.executor.max_concurrent_tasks,
                "available_slots": config.executor.max_concurrent_tasks - _executor.get_running_task_count(),
                "timeout": config.executor.timeout,
                "max_memory_mb": config.executor.max_memory,
            },
            "rate_limit": {
                "enabled": config.rate_limit.enabled,
                "requests_per_minute": config.rate_limit.requests_per_minute,
                "burst_size": config.rate_limit.burst_size,
            }
        }

    return app
