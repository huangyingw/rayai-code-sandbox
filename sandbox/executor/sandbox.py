"""
Sandboxed code executor.

Executes Python code in a restricted subprocess with resource limits.
"""

import asyncio
import logging
import os
import sys
import tempfile
import uuid
from datetime import datetime
from typing import Optional

from ..config import Config, config as default_config
from ..models import Task, TaskStatus
from ..storage import TaskStorage, MemoryStorage
from .wrapper import generate_wrapper


logger = logging.getLogger(__name__)


class SandboxExecutor:
    """Executes Python code in a sandboxed environment."""

    def __init__(
        self,
        storage: Optional[TaskStorage] = None,
        config: Optional[Config] = None,
    ):
        """
        Initialize the executor.

        Args:
            storage: Task storage implementation. Defaults to MemoryStorage.
            config: Configuration. Defaults to global config.
        """
        self.storage = storage or MemoryStorage()
        self.config = config or default_config
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    async def create_task(self, code: str) -> Task:
        """Create a new task and return it."""
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            task_id=task_id,
            code=code,
            status=TaskStatus.PENDING,
        )
        await self.storage.create(task)
        logger.info(f"Created task {task_id}")
        return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        return await self.storage.get(task_id)

    def get_output_buffer(self, task_id: str) -> list[str]:
        """Get the output buffer for streaming."""
        return self.storage.get_output_buffer(task_id)

    async def execute(self, task_id: str) -> Task:
        """Execute the task's code in a sandbox."""
        task = await self.storage.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        await self.storage.update(task)
        logger.info(f"Starting execution of task {task_id}")

        # Generate sandbox wrapper script
        wrapper_code = generate_wrapper(
            code=task.code,
            cpu_time=self.config.executor.timeout,
            memory=self.config.executor.max_memory,
            blocked_modules=self.config.security.blocked_modules,
        )

        # Write to temporary file
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', delete=False
        ) as f:
            f.write(wrapper_code)
            temp_file = f.name

        try:
            # Execute in subprocess
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-u', temp_file,  # -u for unbuffered output
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                close_fds=True,
            )
            self._processes[task_id] = process

            stdout_data = []
            stderr_data = []

            async def read_stream(stream, buffer, is_stdout: bool):
                """Read from stream and update buffers."""
                total_size = 0
                max_size = self.config.executor.max_output_size
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode('utf-8', errors='replace')
                    total_size += len(decoded)
                    if total_size <= max_size:
                        buffer.append(decoded)
                        if is_stdout:
                            self.storage.append_output(task_id, decoded)
                    else:
                        if not any('truncated' in s for s in buffer):
                            msg = '\n[Output truncated due to size limit]\n'
                            buffer.append(msg)
                        break

            try:
                # Read stdout and stderr concurrently with timeout
                timeout = self.config.executor.timeout + 2
                await asyncio.wait_for(
                    asyncio.gather(
                        read_stream(process.stdout, stdout_data, True),
                        read_stream(process.stderr, stderr_data, False),
                    ),
                    timeout=timeout,
                )
                await process.wait()

            except asyncio.TimeoutError:
                logger.warning(f"Task {task_id} timed out")
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass
                task.status = TaskStatus.TIMEOUT
                task.error_message = f"Execution timed out after {self.config.executor.timeout} seconds"
                task.finished_at = datetime.now()
                await self.storage.update(task)
                return task

            task.stdout = ''.join(stdout_data)
            task.stderr = ''.join(stderr_data)
            task.exit_code = process.returncode

            if process.returncode == 0:
                task.status = TaskStatus.COMPLETED
                logger.info(f"Task {task_id} completed successfully")
            elif process.returncode == 137:
                task.status = TaskStatus.TIMEOUT
                task.error_message = "CPU time limit exceeded"
                logger.warning(f"Task {task_id} exceeded CPU time limit")
            elif process.returncode == -9:
                task.status = TaskStatus.KILLED
                task.error_message = "Process was killed (possibly due to memory limit)"
                logger.warning(f"Task {task_id} was killed")
            else:
                task.status = TaskStatus.FAILED
                if task.stderr:
                    task.error_message = task.stderr.strip().split('\n')[-1]
                logger.info(f"Task {task_id} failed with exit code {process.returncode}")

        except Exception as e:
            logger.exception(f"Error executing task {task_id}")
            task.status = TaskStatus.FAILED
            task.error_message = str(e)

        finally:
            # Cleanup
            try:
                os.unlink(temp_file)
            except OSError:
                pass
            if task_id in self._processes:
                del self._processes[task_id]

        task.finished_at = datetime.now()
        await self.storage.update(task)
        return task

    async def kill_task(self, task_id: str) -> bool:
        """Kill a running task."""
        process = self._processes.get(task_id)
        if process:
            try:
                process.kill()
                await process.wait()
                task = await self.storage.get(task_id)
                if task:
                    task.status = TaskStatus.KILLED
                    task.error_message = "Task was manually killed"
                    task.finished_at = datetime.now()
                    await self.storage.update(task)
                logger.info(f"Task {task_id} was killed")
                return True
            except ProcessLookupError:
                pass
        return False
