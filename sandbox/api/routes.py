"""
FastAPI routes for the code executor API.
"""

import asyncio
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..config import config
from ..models import TaskStatus
from ..executor import SandboxExecutor


logger = logging.getLogger(__name__)


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
        """Health check endpoint."""
        return {"status": "healthy"}

    return app
