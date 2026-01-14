"""
Data models for the sandbox.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    KILLED = "killed"


@dataclass
class Task:
    """Represents a code execution task."""
    task_id: str
    code: str
    status: TaskStatus = TaskStatus.PENDING
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert task to dictionary for API response."""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
