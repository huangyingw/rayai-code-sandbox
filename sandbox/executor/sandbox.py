"""
Sandboxed code executor.

Executes Python code in isolated Docker containers with resource limits.
Docker is mandatory for security.
"""

import asyncio
import logging
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime
from typing import Optional, Tuple

from ..config import Config, config as default_config
from ..models import Task, TaskStatus
from ..storage import TaskStorage, MemoryStorage
from .docker import DockerRunner
from .wrapper import generate_wrapper


logger = logging.getLogger(__name__)


class ConcurrencyLimitExceeded(Exception):
    """Raised when the maximum number of concurrent tasks is exceeded."""
    pass


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
        # Semaphore to limit concurrent executions
        self._semaphore = asyncio.Semaphore(self.config.executor.max_concurrent_tasks)
        # Docker runner for container execution
        self._docker = DockerRunner(self.config.docker)

    def get_running_task_count(self) -> int:
        """Get the number of currently running tasks."""
        return len(self._processes)

    def get_available_slots(self) -> int:
        """Get the number of available execution slots."""
        return self.config.executor.max_concurrent_tasks - self.get_running_task_count()

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

    async def _is_docker_available(self) -> bool:
        """Check if Docker is available and accessible."""
        if not shutil.which("docker"):
            return False
        try:
            # Try to run docker info to check if we have permission
            proc = await asyncio.create_subprocess_exec(
                "docker", "info",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=2.0)
            return proc.returncode == 0
        except (asyncio.TimeoutError, Exception):
            return False

    def _validate_code(self, code: str) -> Tuple[bool, Optional[str]]:
        """Validate user code before execution.

        Returns:
            (is_valid, error_message)
        """
        # Check for empty or whitespace-only code
        if not code or not code.strip():
            return False, "Empty code is not allowed"

        # Check code length
        if len(code) > self.config.executor.max_code_size:
            return False, f"Code exceeds maximum length ({self.config.executor.max_code_size} characters)"

        # Validate UTF-8 encoding
        try:
            code.encode('utf-8').decode('utf-8')
        except UnicodeError as e:
            return False, f"Invalid encoding in code: {e}"

        # Try to compile the code to check for syntax errors
        try:
            compile(code, '<user_code>', 'exec')
        except SyntaxError as e:
            return False, f"SyntaxError: {e.msg} at line {e.lineno}"

        return True, None

    async def execute(self, task_id: str, wait_for_slot: bool = True) -> Task:
        """Execute the task's code in a sandbox.

        Args:
            task_id: The task ID to execute.
            wait_for_slot: If True, wait for an available slot. If False, fail immediately
                          when no slots are available.
        """
        task = await self.storage.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Try to acquire semaphore for concurrent execution limit
        if wait_for_slot:
            await self._semaphore.acquire()
        else:
            # Try to acquire without waiting
            if self._semaphore.locked() and self._semaphore._value == 0:
                task.status = TaskStatus.FAILED
                task.error_message = f"Server busy: maximum concurrent tasks ({self.config.executor.max_concurrent_tasks}) reached"
                task.stderr = task.error_message + "\n"
                task.exit_code = 1
                task.finished_at = datetime.now()
                await self.storage.update(task)
                logger.warning(f"Task {task_id} rejected: concurrency limit reached")
                return task
            await self._semaphore.acquire()

        try:
            return await self._execute_internal(task_id, task)
        finally:
            self._semaphore.release()

    async def _execute_internal(self, task_id: str, task: Task) -> Task:
        """Internal execution method called after acquiring semaphore."""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        await self.storage.update(task)
        logger.info(f"Starting execution of task {task_id}")

        # Validate code before execution
        is_valid, error_msg = self._validate_code(task.code)
        if not is_valid:
            task.status = TaskStatus.FAILED
            task.error_message = error_msg
            task.stderr = error_msg + "\n"
            task.exit_code = 1
            task.finished_at = datetime.now()
            await self.storage.update(task)
            logger.info(f"Task {task_id} failed validation: {error_msg}")
            return task

        # Generate sandbox wrapper script (used inside Docker container)
        wrapper_code = generate_wrapper(
            code=task.code,
            cpu_time=self.config.executor.timeout,
            memory=self.config.executor.max_memory,
            recursion_limit=self.config.executor.recursion_limit,
            allowed_modules=self.config.security.allowed_modules,
        )

        # Write to temporary file (must be in /tmp for Docker mount)
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', delete=False, dir='/tmp'
        ) as f:
            f.write(wrapper_code)
            temp_file = f.name
        # Make file readable by Docker's nobody user (65534)
        os.chmod(temp_file, 0o644)

        try:
            # Check if Docker is available and accessible
            use_docker = await self._is_docker_available()
            if use_docker:
                cmd = self._docker.build_docker_command(task_id, temp_file)
                logger.debug(f"Docker command for task {task_id}: {' '.join(cmd[:10])}...")
            else:
                # Fallback to subprocess execution (less secure, for development/testing)
                logger.warning(f"Docker not available for task {task_id}, using subprocess fallback")
                cmd = [sys.executable, '-u', temp_file]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
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
            elif process.returncode == 137 or process.returncode == -24:
                # 137 = 128 + 9 (SIGKILL after SIGXCPU)
                # -24 = SIGXCPU
                task.status = TaskStatus.TIMEOUT
                task.error_message = "CPU time limit exceeded"
                logger.warning(f"Task {task_id} exceeded CPU time limit")
            elif process.returncode == -9 or process.returncode == 128 + 9:
                task.status = TaskStatus.KILLED
                task.error_message = "Process was killed (possibly due to memory limit)"
                logger.warning(f"Task {task_id} was killed")
            elif process.returncode == -6 or process.returncode == 128 + 6:
                # SIGABRT - often from memory allocation failure
                task.status = TaskStatus.FAILED
                task.error_message = "Process aborted (memory allocation failure)"
                logger.warning(f"Task {task_id} aborted")
            else:
                task.status = TaskStatus.FAILED
                # Extract meaningful error message from stderr
                if task.stderr:
                    stderr_lines = task.stderr.strip().split('\n')
                    # Check for specific error types first
                    if 'RecursionError' in task.stderr:
                        task.error_message = "RecursionError: maximum recursion depth exceeded"
                    elif 'MemoryError' in task.stderr:
                        task.error_message = "MemoryError: out of memory"
                    else:
                        # Look for common Python error patterns
                        for line in reversed(stderr_lines):
                            if ': ' in line and any(err in line for err in [
                                'Error', 'Exception', 'Traceback'
                            ]):
                                task.error_message = line
                                break
                        else:
                            task.error_message = stderr_lines[-1] if stderr_lines else None
                else:
                    task.error_message = f"Process exited with code {process.returncode}"
                logger.info(f"Task {task_id} failed with exit code {process.returncode}")

        except Exception as e:
            logger.exception(f"Error executing task {task_id}")
            task.status = TaskStatus.FAILED
            task.error_message = f"Execution error: {type(e).__name__}: {e}"

        finally:
            # Cleanup
            try:
                os.unlink(temp_file)
            except OSError:
                pass
            if task_id in self._processes:
                del self._processes[task_id]
            # Clean up Docker container name mapping
            self._docker.cleanup_task(task_id)

        task.finished_at = datetime.now()
        await self.storage.update(task)
        return task

    async def kill_task(self, task_id: str) -> bool:
        """Kill a running task and its Docker container."""
        process = self._processes.get(task_id)
        killed = False

        # Kill the Docker container
        await self._docker.kill_container(task_id)

        # Kill the process if still running
        if process:
            try:
                process.kill()
                await process.wait()
                killed = True
            except ProcessLookupError:
                killed = True  # Already dead

        if killed or task_id in self._processes:
            task = await self.storage.get(task_id)
            if task:
                task.status = TaskStatus.KILLED
                task.error_message = "Task was manually killed"
                task.finished_at = datetime.now()
                await self.storage.update(task)
            logger.info(f"Task {task_id} was killed")
            self._processes.pop(task_id, None)
            self._docker.cleanup_task(task_id)
            return True

        return False
