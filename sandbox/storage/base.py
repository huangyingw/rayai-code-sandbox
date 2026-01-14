"""
Abstract base class for task storage.
"""

from abc import ABC, abstractmethod
from typing import Optional, List

from ..models import Task


class TaskStorage(ABC):
    """Abstract base class for task storage implementations."""

    @abstractmethod
    async def create(self, task: Task) -> Task:
        """Create a new task."""
        pass

    @abstractmethod
    async def get(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        pass

    @abstractmethod
    async def update(self, task: Task) -> Task:
        """Update an existing task."""
        pass

    @abstractmethod
    async def delete(self, task_id: str) -> bool:
        """Delete a task by ID."""
        pass

    @abstractmethod
    async def list_all(self, limit: int = 100) -> List[Task]:
        """List all tasks."""
        pass

    @abstractmethod
    def get_output_buffer(self, task_id: str) -> List[str]:
        """Get the output buffer for streaming."""
        pass

    @abstractmethod
    def append_output(self, task_id: str, line: str) -> None:
        """Append a line to the output buffer."""
        pass
