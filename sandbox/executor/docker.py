"""
Docker-based code executor.

Executes Python code in isolated Docker containers for maximum security.
Each task runs in its own container with strict resource limits.
"""

import asyncio
import logging
import os
from typing import Optional

from ..config import DockerConfig


logger = logging.getLogger(__name__)


# Get project root directory (where Dockerfile.sandbox is located)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DockerExecutionError(Exception):
    """Raised when Docker execution fails."""
    pass


class DockerRunner:
    """Handles Docker container execution for code sandboxing."""

    def __init__(self, docker_config: Optional[DockerConfig] = None):
        """
        Initialize Docker runner.

        Args:
            docker_config: Docker configuration. Uses defaults if not provided.
        """
        self.config = docker_config or DockerConfig()
        self._container_names: dict[str, str] = {}

    def _get_seccomp_path(self) -> Optional[str]:
        """Get path to seccomp profile if available."""
        seccomp_path = os.path.join(PROJECT_ROOT, "seccomp-profile.json")
        if os.path.exists(seccomp_path):
            return seccomp_path
        return None

    def build_docker_command(self, task_id: str, script_path: str) -> list[str]:
        """
        Build Docker run command with security restrictions.

        Args:
            task_id: Unique task identifier for container naming.
            script_path: Path to the Python script to execute.

        Returns:
            List of command arguments for docker run.
        """
        # Use task_id for consistent container naming
        container_name = f"sandbox-{task_id}"
        self._container_names[task_id] = container_name

        cmd = [
            "docker", "run",
            "--rm",  # Remove container after exit
            "--name", container_name,

            # Resource limits
            f"--memory={self.config.memory_limit}",
            f"--memory-swap={self.config.memory_limit}",  # No swap
            f"--cpus={self.config.cpu_limit}",
            f"--pids-limit={self.config.pids_limit}",

            # Network isolation
            f"--network={self.config.network}",

            # Security options
            "--security-opt=no-new-privileges:true",
            "--cap-drop=ALL",  # Drop all capabilities
        ]

        # Read-only filesystem with tmpfs for temp files
        if self.config.read_only:
            cmd.extend([
                "--read-only",
                "--tmpfs=/tmp:size=10m,noexec,nosuid,nodev",
            ])

        # Add seccomp profile if available
        seccomp_path = self._get_seccomp_path()
        if seccomp_path:
            cmd.extend(["--security-opt", f"seccomp={seccomp_path}"])

        cmd.extend([
            # User namespace (run as nobody)
            f"--user={self.config.user}",

            # Mount script read-only
            "-v", f"{script_path}:/sandbox/script.py:ro",

            # Image and command
            self.config.image,
            "python3", "-u", "/sandbox/script.py",
        ])

        return cmd

    async def kill_container(self, task_id: str) -> bool:
        """
        Kill a running container.

        Args:
            task_id: Task ID whose container should be killed.

        Returns:
            True if container was killed, False otherwise.
        """
        container_name = self._container_names.get(task_id, f"sandbox-{task_id}")
        try:
            kill_proc = await asyncio.create_subprocess_exec(
                "docker", "kill", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await kill_proc.wait()
            self._container_names.pop(task_id, None)
            logger.info(f"Killed container for task {task_id}")
            return kill_proc.returncode == 0
        except Exception as e:
            logger.warning(f"Failed to kill container for task {task_id}: {e}")
            return False

    def cleanup_task(self, task_id: str):
        """Clean up container name mapping for a task."""
        self._container_names.pop(task_id, None)
