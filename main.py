"""
Code Executor Sandbox API

A secure HTTP API for executing arbitrary Python code with real-time streaming output.

Security features:
- Docker container isolation (when available)
- Resource limits (CPU, memory, processes)
- Network isolation
- Restricted Python builtins
- Module whitelist
"""

import asyncio
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Choose executor based on environment
USE_DOCKER = os.getenv("USE_DOCKER", "auto").lower()

if USE_DOCKER == "true":
    from docker_executor import DockerExecutor as Executor, TaskStatus
    use_docker = True
elif USE_DOCKER == "false":
    from executor import CodeExecutor as Executor, TaskStatus
    use_docker = False
else:  # auto
    try:
        from docker_executor import DockerExecutor as Executor, TaskStatus
        use_docker = Executor.is_docker_available()
    except ImportError:
        from executor import CodeExecutor as Executor, TaskStatus
        use_docker = False


app = FastAPI(
    title="Code Executor Sandbox",
    description="Execute Python code safely with streaming output",
    version="1.1.0",
)

# Global executor instance
executor = Executor(
    timeout=10,  # 10 seconds max execution time
    max_memory=128,  # 128MB max memory
    max_output_size=1024 * 1024,  # 1MB max output
    **({"use_docker": use_docker} if hasattr(Executor, "__init__") and "use_docker" in Executor.__init__.__code__.co_varnames else {}),
)


class ExecuteRequest(BaseModel):
    """Request body for code execution."""
    code: str = Field(..., description="Python code to execute", min_length=1, max_length=100000)


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


@app.post("/execute", response_model=ExecuteResponse)
async def execute_code(request: ExecuteRequest, background_tasks: BackgroundTasks):
    """
    Submit Python code for execution.

    Returns a task_id that can be used to track execution status and stream output.
    """
    # Create task
    task_id = executor.create_task(request.code)

    # Execute in background
    background_tasks.add_task(executor.execute, task_id, request.code)

    return ExecuteResponse(task_id=task_id)


@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    """
    Get the status and result of a task.
    """
    task = executor.get_task(task_id)
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
    task = executor.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    async def event_generator():
        """Generate SSE events for task output."""
        last_index = 0

        while True:
            # Get current task status
            current_task = executor.get_task(task_id)
            if not current_task:
                break

            # Get new output lines
            buffer = executor.get_output_buffer(task_id)
            while last_index < len(buffer):
                line = buffer[last_index]
                # Format as SSE
                yield f"data: {line}\n\n"
                last_index += 1

            # Check if task is done
            if current_task.status in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.TIMEOUT,
                TaskStatus.KILLED,
            ):
                # Send final status
                yield f"event: status\ndata: {current_task.status.value}\n\n"
                if current_task.error_message:
                    yield f"event: error\ndata: {current_task.error_message}\n\n"
                yield "event: done\ndata: finished\n\n"
                break

            # Small delay to prevent busy loop
            await asyncio.sleep(0.1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.delete("/tasks/{task_id}")
async def kill_task(task_id: str):
    """
    Kill a running task.
    """
    task = executor.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if task.status != TaskStatus.RUNNING:
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} is not running (status: {task.status})"
        )

    killed = await executor.kill_task(task_id)
    if killed:
        return {"message": f"Task {task_id} killed successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to kill task")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/info")
async def get_info():
    """Get sandbox configuration and security info."""
    return {
        "version": "1.1.0",
        "docker_enabled": use_docker,
        "security_features": {
            "container_isolation": use_docker,
            "network_isolation": use_docker,
            "resource_limits": True,
            "restricted_builtins": True,
            "module_whitelist": True,
        },
        "limits": {
            "timeout_seconds": executor.timeout,
            "max_memory_mb": executor.max_memory,
            "max_output_bytes": executor.max_output_size,
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
