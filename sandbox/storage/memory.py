"""
In-memory storage implementation.

Simple dictionary-based storage for development and single-instance deployments.
"""

from typing import Optional, List

from .base import TaskStorage
from ..models import Task


class MemoryStorage(TaskStorage):
    """In-memory task storage using dictionaries."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._output_buffers: dict[str, List[str]] = {}

    async def create(self, task: Task) -> Task:
        """Create a new task."""
        self._tasks[task.task_id] = task
        self._output_buffers[task.task_id] = []
        return task

    async def get(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    async def update(self, task: Task) -> Task:
        """Update an existing task."""
        if task.task_id not in self._tasks:
            raise KeyError(f"Task {task.task_id} not found")
        self._tasks[task.task_id] = task
        return task

    async def delete(self, task_id: str) -> bool:
        """Delete a task by ID."""
        if task_id in self._tasks:
            del self._tasks[task_id]
            if task_id in self._output_buffers:
                del self._output_buffers[task_id]
            return True
        return False

    async def list_all(self, limit: int = 100) -> List[Task]:
        """List all tasks."""
        tasks = list(self._tasks.values())
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)[:limit]

    def get_output_buffer(self, task_id: str) -> List[str]:
        """Get the output buffer for streaming."""
        return self._output_buffers.get(task_id, [])

    def append_output(self, task_id: str, line: str) -> None:
        """Append a line to the output buffer."""
        if task_id in self._output_buffers:
            self._output_buffers[task_id].append(line)
