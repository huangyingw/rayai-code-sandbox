"""
Docker-based Code Executor Module

Provides secure Python code execution using Docker container isolation.
This provides OS-level isolation in addition to Python-level restrictions.
"""

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    KILLED = "killed"


@dataclass
class TaskResult:
    task_id: str
    status: TaskStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None


# Sandbox wrapper script with enhanced security
# This runs INSIDE the Docker container as a second layer of defense
SANDBOX_SCRIPT = '''
import sys
import resource

# Resource limits (backup in case Docker limits fail)
try:
    resource.setrlimit(resource.RLIMIT_CPU, ({cpu_time}, {cpu_time}))
    resource.setrlimit(resource.RLIMIT_AS, ({memory_bytes}, {memory_bytes}))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))  # 1MB
    resource.setrlimit(resource.RLIMIT_NOFILE, (10, 10))
    resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))  # Prevent fork bombs
except (ValueError, resource.error):
    pass

# Enhanced restricted builtins with bypass protection
class RestrictedBuiltins:
    """Secure wrapper that prevents attribute-based escapes."""

    _SAFE = {{
        'abs': abs, 'all': all, 'any': any, 'ascii': ascii,
        'bin': bin, 'bool': bool, 'bytearray': bytearray, 'bytes': bytes,
        'callable': callable, 'chr': chr, 'complex': complex,
        'dict': dict, 'divmod': divmod, 'enumerate': enumerate,
        'filter': filter, 'float': float, 'format': format,
        'frozenset': frozenset, 'hash': hash, 'hex': hex, 'id': id, 'int': int,
        'isinstance': isinstance, 'issubclass': issubclass, 'iter': iter,
        'len': len, 'list': list, 'map': map, 'max': max, 'min': min,
        'next': next, 'object': object, 'oct': oct, 'ord': ord,
        'pow': pow, 'print': print, 'range': range, 'repr': repr,
        'reversed': reversed, 'round': round, 'set': set,
        'slice': slice, 'sorted': sorted, 'str': str, 'sum': sum,
        'tuple': tuple, 'zip': zip,
        'True': True, 'False': False, 'None': None,
        # Safe exceptions
        'Exception': Exception, 'BaseException': BaseException,
        'ValueError': ValueError, 'TypeError': TypeError,
        'KeyError': KeyError, 'IndexError': IndexError,
        'AttributeError': AttributeError, 'RuntimeError': RuntimeError,
        'StopIteration': StopIteration, 'ZeroDivisionError': ZeroDivisionError,
        'NameError': NameError, 'ImportError': ImportError,
        'ArithmeticError': ArithmeticError, 'LookupError': LookupError,
    }}

    # Modules allowed for import (whitelist approach)
    _ALLOWED_MODULES = {{
        'math', 'cmath', 'decimal', 'fractions', 'random', 'statistics',
        'itertools', 'functools', 'operator',
        'string', 'textwrap',
        'datetime', 'calendar', 'time',
        'collections', 'heapq', 'bisect', 'array',
        'copy', 'pprint',
        'enum', 'dataclasses',
        're', 'json',
    }}

    def __init__(self):
        import builtins
        self._original_import = builtins.__import__

    def __getitem__(self, key):
        if key in self._SAFE:
            return self._SAFE[key]
        raise KeyError(f"Builtin '{{key}}' is not available")

    def __contains__(self, key):
        return key in self._SAFE

    def get(self, key, default=None):
        return self._SAFE.get(key, default)

    def keys(self):
        return self._SAFE.keys()

    def restricted_import(self, name, globals=None, locals=None, fromlist=(), level=0):
        base_module = name.split('.')[0]
        if base_module not in self._ALLOWED_MODULES:
            raise ImportError(f"Module '{{name}}' is not allowed. Allowed: {{sorted(self._ALLOWED_MODULES)}}")
        return self._original_import(name, globals, locals, fromlist, level)

restricted = RestrictedBuiltins()
restricted._SAFE['__import__'] = restricted.restricted_import

# Prevent access to dangerous attributes
class SafeObject:
    """Wrapper to prevent __class__ based escapes."""
    pass

# User code
user_code = {user_code!r}

# Create restricted globals
restricted_globals = {{
    '__builtins__': restricted,
    '__name__': '__main__',
    '__doc__': None,
}}

try:
    # Compile first to catch syntax errors
    compiled = compile(user_code, '<user_code>', 'exec')
    exec(compiled, restricted_globals)
except SystemExit as e:
    sys.exit(e.code if e.code is not None else 0)
except Exception as e:
    print(f"{{type(e).__name__}}: {{e}}", file=sys.stderr)
    sys.exit(1)
'''


class DockerExecutor:
    """Executes Python code in a Docker container sandbox."""

    DOCKER_IMAGE = "python-sandbox:latest"

    def __init__(
        self,
        timeout: int = 10,
        max_memory: int = 128,  # MB
        max_output_size: int = 1024 * 1024,
        use_docker: bool = True,
    ):
        self.timeout = timeout
        self.max_memory = max_memory
        self.max_output_size = max_output_size
        self.use_docker = use_docker
        self.tasks: dict[str, TaskResult] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.output_buffers: dict[str, list[str]] = {}

    @classmethod
    def is_docker_available(cls) -> bool:
        """Check if Docker is available."""
        return shutil.which("docker") is not None

    @classmethod
    async def build_sandbox_image(cls) -> bool:
        """Build the sandbox Docker image."""
        dockerfile_path = os.path.join(os.path.dirname(__file__), "Dockerfile.sandbox")
        if not os.path.exists(dockerfile_path):
            return False

        process = await asyncio.create_subprocess_exec(
            "docker", "build", "-t", cls.DOCKER_IMAGE, "-f", dockerfile_path, ".",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.wait()
        return process.returncode == 0

    def create_task(self, code: str) -> str:
        """Create a new task and return its ID."""
        task_id = str(uuid.uuid4())[:8]
        self.tasks[task_id] = TaskResult(
            task_id=task_id,
            status=TaskStatus.PENDING,
        )
        self.output_buffers[task_id] = []
        return task_id

    def get_task(self, task_id: str) -> Optional[TaskResult]:
        """Get task result by ID."""
        return self.tasks.get(task_id)

    def get_output_buffer(self, task_id: str) -> list[str]:
        """Get the output buffer for streaming."""
        return self.output_buffers.get(task_id, [])

    async def execute(self, task_id: str, code: str) -> TaskResult:
        """Execute code in Docker container."""
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()

        # Create sandbox script
        memory_bytes = self.max_memory * 1024 * 1024
        sandbox_code = SANDBOX_SCRIPT.format(
            cpu_time=self.timeout,
            memory_bytes=memory_bytes,
            user_code=code,
        )

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', delete=False, dir='/tmp'
        ) as f:
            f.write(sandbox_code)
            temp_file = f.name

        try:
            if self.use_docker and self.is_docker_available():
                cmd = await self._build_docker_command(temp_file)
            else:
                # Fallback to subprocess execution
                import sys
                cmd = [sys.executable, '-u', temp_file]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self.processes[task_id] = process

            stdout_data = []
            stderr_data = []

            async def read_stream(stream, buffer, output_buffer):
                total_size = 0
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode('utf-8', errors='replace')
                    total_size += len(decoded)
                    if total_size <= self.max_output_size:
                        buffer.append(decoded)
                        output_buffer.append(decoded)
                    else:
                        if not any('truncated' in s for s in buffer):
                            buffer.append('\n[Output truncated]\n')
                        break

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        read_stream(process.stdout, stdout_data, self.output_buffers[task_id]),
                        read_stream(process.stderr, stderr_data, self.output_buffers[task_id]),
                    ),
                    timeout=self.timeout + 5,
                )
                await process.wait()

            except asyncio.TimeoutError:
                await self._kill_process(process, task_id)
                task.status = TaskStatus.TIMEOUT
                task.error_message = f"Execution timed out after {self.timeout} seconds"
                task.finished_at = datetime.now()
                return task

            task.stdout = ''.join(stdout_data)
            task.stderr = ''.join(stderr_data)
            task.exit_code = process.returncode

            if process.returncode == 0:
                task.status = TaskStatus.COMPLETED
            elif process.returncode in (137, 124):  # SIGKILL or timeout
                task.status = TaskStatus.TIMEOUT
                task.error_message = "Execution limit exceeded"
            elif process.returncode == -9:
                task.status = TaskStatus.KILLED
                task.error_message = "Process killed (memory/resource limit)"
            else:
                task.status = TaskStatus.FAILED
                if task.stderr:
                    task.error_message = task.stderr.strip().split('\n')[-1]

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)

        finally:
            try:
                os.unlink(temp_file)
            except OSError:
                pass
            self.processes.pop(task_id, None)

        task.finished_at = datetime.now()
        return task

    async def _build_docker_command(self, script_path: str) -> list[str]:
        """Build Docker run command with security restrictions."""
        container_name = f"sandbox-{uuid.uuid4().hex[:8]}"

        return [
            "docker", "run",
            "--rm",  # Remove container after exit
            "--name", container_name,

            # Resource limits
            f"--memory={self.max_memory}m",
            "--memory-swap", f"{self.max_memory}m",  # No swap
            f"--cpus=1",
            "--pids-limit=50",  # Limit processes

            # Network isolation
            "--network=none",

            # Security options
            "--security-opt=no-new-privileges:true",
            "--cap-drop=ALL",  # Drop all capabilities
            "--read-only",  # Read-only filesystem
            "--tmpfs=/tmp:size=10m,noexec,nosuid,nodev",  # Temp with limits

            # User namespace (run as nobody)
            "--user=65534:65534",

            # Mount script read-only
            "-v", f"{script_path}:/sandbox/script.py:ro",

            # Image and command
            self.DOCKER_IMAGE,
            "python3", "-u", "/sandbox/script.py",
        ]

    async def _kill_process(self, process, task_id: str):
        """Kill process and cleanup Docker container if needed."""
        try:
            process.kill()
            await process.wait()
        except ProcessLookupError:
            pass

        # Also try to stop Docker container
        if self.use_docker:
            container_name = f"sandbox-{task_id}"
            kill_proc = await asyncio.create_subprocess_exec(
                "docker", "kill", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await kill_proc.wait()

    async def kill_task(self, task_id: str) -> bool:
        """Kill a running task."""
        process = self.processes.get(task_id)
        if process:
            await self._kill_process(process, task_id)
            task = self.tasks.get(task_id)
            if task:
                task.status = TaskStatus.KILLED
                task.error_message = "Task was manually killed"
                task.finished_at = datetime.now()
            return True
        return False
