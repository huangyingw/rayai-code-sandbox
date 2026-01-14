"""
Code Executor Module

Provides sandboxed Python code execution with security measures.
"""

import asyncio
import os
import resource
import signal
import sys
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


# Security: List of dangerous modules/patterns to block
BLOCKED_IMPORTS = [
    "os", "subprocess", "shutil", "sys", "importlib",
    "ctypes", "multiprocessing", "threading", "socket",
    "http", "urllib", "requests", "ftplib", "smtplib",
    "pickle", "marshal", "shelve", "dbm",
    "code", "codeop", "compile", "exec", "eval",
    "builtins", "__builtins__",
    "pty", "tty", "termios", "fcntl",
    "resource", "signal", "gc",
    "ast", "dis", "inspect", "traceback",
]

# Wrapper script that sets up resource limits and restricted execution
SANDBOX_WRAPPER = '''
import sys
import resource
import signal

# Set resource limits
MAX_CPU_TIME = {cpu_time}  # seconds
MAX_MEMORY = {memory} * 1024 * 1024  # bytes
MAX_FILE_SIZE = 1024 * 1024  # 1MB
MAX_OPEN_FILES = 10

try:
    resource.setrlimit(resource.RLIMIT_CPU, (MAX_CPU_TIME, MAX_CPU_TIME))
    resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY, MAX_MEMORY))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_SIZE, MAX_FILE_SIZE))
    resource.setrlimit(resource.RLIMIT_NOFILE, (MAX_OPEN_FILES, MAX_OPEN_FILES))
except (ValueError, resource.error):
    pass  # Some limits may not be available on all systems

# Set up signal handler for CPU time limit
def timeout_handler(signum, frame):
    print("Error: CPU time limit exceeded", file=sys.stderr)
    sys.exit(137)

signal.signal(signal.SIGXCPU, timeout_handler)

# Restricted builtins - remove dangerous functions
import builtins

_safe_builtins = {{
    'abs': abs, 'all': all, 'any': any, 'ascii': ascii,
    'bin': bin, 'bool': bool, 'bytearray': bytearray, 'bytes': bytes,
    'callable': callable, 'chr': chr, 'complex': complex,
    'dict': dict, 'divmod': divmod, 'enumerate': enumerate,
    'filter': filter, 'float': float, 'format': format,
    'frozenset': frozenset, 'getattr': getattr, 'hasattr': hasattr,
    'hash': hash, 'hex': hex, 'id': id, 'int': int,
    'isinstance': isinstance, 'issubclass': issubclass, 'iter': iter,
    'len': len, 'list': list, 'map': map, 'max': max, 'min': min,
    'next': next, 'object': object, 'oct': oct, 'ord': ord,
    'pow': pow, 'print': print, 'range': range, 'repr': repr,
    'reversed': reversed, 'round': round, 'set': set,
    'slice': slice, 'sorted': sorted, 'str': str, 'sum': sum,
    'tuple': tuple, 'type': type, 'zip': zip,
    'True': True, 'False': False, 'None': None,
    'Exception': Exception, 'BaseException': BaseException,
    'ValueError': ValueError, 'TypeError': TypeError,
    'KeyError': KeyError, 'IndexError': IndexError,
    'AttributeError': AttributeError, 'RuntimeError': RuntimeError,
    'StopIteration': StopIteration, 'ZeroDivisionError': ZeroDivisionError,
}}

# Block dangerous builtins
blocked_builtins = ['eval', 'exec', 'compile', 'open', 'input', '__import__',
                    'globals', 'locals', 'vars', 'dir', 'getattr', 'setattr',
                    'delattr', 'breakpoint', 'memoryview', 'help']

# Create restricted __builtins__
restricted_builtins = dict(_safe_builtins)

# Custom import function that blocks dangerous modules
_original_import = builtins.__import__
BLOCKED_MODULES = {blocked_modules}

def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    # Check if the base module is blocked
    base_module = name.split('.')[0]
    if base_module in BLOCKED_MODULES:
        raise ImportError(f"Import of '{{name}}' is not allowed for security reasons")
    return _original_import(name, globals, locals, fromlist, level)

restricted_builtins['__import__'] = _restricted_import

# Execute user code
user_code = {user_code!r}

try:
    exec(user_code, {{'__builtins__': restricted_builtins, '__name__': '__main__'}})
except SystemExit as e:
    sys.exit(e.code if e.code is not None else 0)
except Exception as e:
    print(f"{{type(e).__name__}}: {{e}}", file=sys.stderr)
    sys.exit(1)
'''


class CodeExecutor:
    """Executes Python code in a sandboxed environment."""

    def __init__(
        self,
        timeout: int = 10,  # seconds
        max_memory: int = 128,  # MB
        max_output_size: int = 1024 * 1024,  # 1MB
    ):
        self.timeout = timeout
        self.max_memory = max_memory
        self.max_output_size = max_output_size
        self.tasks: dict[str, TaskResult] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.output_buffers: dict[str, list[str]] = {}

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
        """Execute code and update task result."""
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()

        # Create the sandbox wrapper script
        blocked_modules_str = repr(BLOCKED_IMPORTS)
        wrapper_code = SANDBOX_WRAPPER.format(
            cpu_time=self.timeout,
            memory=self.max_memory,
            blocked_modules=blocked_modules_str,
            user_code=code,
        )

        # Write wrapper to temp file
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', delete=False
        ) as f:
            f.write(wrapper_code)
            temp_file = f.name

        try:
            # Execute in subprocess with timeout
            process = await asyncio.create_subprocess_exec(
                sys.executable, temp_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Prevent the process from inheriting file descriptors
                close_fds=True,
            )
            self.processes[task_id] = process

            stdout_data = []
            stderr_data = []

            async def read_stream(stream, buffer, output_buffer):
                """Read from stream and update buffers."""
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
                        # Output truncated
                        if not any('truncated' in s for s in buffer):
                            buffer.append('\n[Output truncated due to size limit]\n')
                        break

            try:
                # Read stdout and stderr concurrently with timeout
                await asyncio.wait_for(
                    asyncio.gather(
                        read_stream(process.stdout, stdout_data, self.output_buffers[task_id]),
                        read_stream(process.stderr, stderr_data, self.output_buffers[task_id]),
                    ),
                    timeout=self.timeout + 2,  # Extra buffer for cleanup
                )
                await process.wait()

            except asyncio.TimeoutError:
                # Kill the process
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass
                task.status = TaskStatus.TIMEOUT
                task.error_message = f"Execution timed out after {self.timeout} seconds"
                task.finished_at = datetime.now()
                return task

            task.stdout = ''.join(stdout_data)
            task.stderr = ''.join(stderr_data)
            task.exit_code = process.returncode

            if process.returncode == 0:
                task.status = TaskStatus.COMPLETED
            elif process.returncode == 137:
                task.status = TaskStatus.TIMEOUT
                task.error_message = "CPU time limit exceeded"
            elif process.returncode == -9:
                task.status = TaskStatus.KILLED
                task.error_message = "Process was killed (possibly due to memory limit)"
            else:
                task.status = TaskStatus.FAILED
                if task.stderr:
                    task.error_message = task.stderr.strip().split('\n')[-1]

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)

        finally:
            # Cleanup
            try:
                os.unlink(temp_file)
            except OSError:
                pass
            if task_id in self.processes:
                del self.processes[task_id]

        task.finished_at = datetime.now()
        return task

    async def kill_task(self, task_id: str) -> bool:
        """Kill a running task."""
        process = self.processes.get(task_id)
        if process:
            try:
                process.kill()
                await process.wait()
                task = self.tasks.get(task_id)
                if task:
                    task.status = TaskStatus.KILLED
                    task.error_message = "Task was manually killed"
                    task.finished_at = datetime.now()
                return True
            except ProcessLookupError:
                pass
        return False
