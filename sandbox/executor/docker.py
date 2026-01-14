"""
Docker-based code executor.

Executes Python code in isolated Docker containers for maximum security.
Each task runs in its own container with strict resource limits.
"""

import asyncio
import logging
import os
import tempfile
from typing import Optional

from ..config import Config, DockerConfig


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


def generate_docker_wrapper(
    code: str,
    cpu_time: int,
    memory_mb: int,
    allowed_modules: list[str],
) -> str:
    """
    Generate the sandbox wrapper script for Docker execution.

    This script runs INSIDE the Docker container and provides a second
    layer of security (defense in depth).

    Args:
        code: User code to execute.
        cpu_time: CPU time limit in seconds.
        memory_mb: Memory limit in megabytes.
        allowed_modules: List of allowed module names.

    Returns:
        Complete wrapper script as a string.
    """
    memory_bytes = memory_mb * 1024 * 1024
    allowed_set = repr(set(allowed_modules))

    return f'''
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

# =============================================================================
# SECURITY: Block dangerous attribute access (__class__, __bases__, etc.)
# This prevents sandbox escapes like: ().__class__.__bases__[0].__subclasses__()
# =============================================================================
BLOCKED_ATTRS = frozenset({{
    '__class__', '__bases__', '__mro__', '__subclasses__',
    '__globals__', '__code__', '__closure__', '__func__',
    '__self__', '__dict__', '__weakref__',
    '__init_subclass__', '__set_name__',
    '__reduce__', '__reduce_ex__',  # Pickle-based attacks
    '__getattribute__', '__setattr__', '__delattr__',
    '__dir__',
}})

_original_getattr = getattr

def _safe_getattr(obj, name, *default):
    """Restricted getattr that blocks dangerous attributes."""
    if isinstance(name, str) and name in BLOCKED_ATTRS:
        raise AttributeError(f"Access to '{{name}}' is not allowed for security reasons")
    return _original_getattr(obj, name, *default) if default else _original_getattr(obj, name)

# Patch getattr globally
import builtins
builtins.getattr = _safe_getattr

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
        'next': next, 'oct': oct, 'ord': ord,
        'pow': pow, 'print': print, 'range': range, 'repr': repr,
        'reversed': reversed, 'round': round, 'set': set,
        'slice': slice, 'sorted': sorted, 'str': str, 'sum': sum,
        'tuple': tuple, 'zip': zip,
        'True': True, 'False': False, 'None': None,
        # Safe getattr (patched version)
        'getattr': _safe_getattr,
        'hasattr': hasattr,
        # Safe exceptions
        'Exception': Exception, 'BaseException': BaseException,
        'ValueError': ValueError, 'TypeError': TypeError,
        'KeyError': KeyError, 'IndexError': IndexError,
        'AttributeError': AttributeError, 'RuntimeError': RuntimeError,
        'StopIteration': StopIteration, 'ZeroDivisionError': ZeroDivisionError,
        'NameError': NameError, 'ImportError': ImportError,
        'ArithmeticError': ArithmeticError, 'LookupError': LookupError,
        'RecursionError': RecursionError, 'MemoryError': MemoryError,
    }}

    # Modules allowed for import (whitelist approach)
    _ALLOWED_MODULES = {allowed_set}

    def __init__(self):
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

# User code
user_code = {code!r}

# =============================================================================
# SECURITY: Detect dangerous patterns in code
# =============================================================================
DANGEROUS_PATTERNS = [
    '__class__', '__bases__', '__mro__', '__subclasses__',
    '__globals__', '__code__', '__builtins__',
]

for pattern in DANGEROUS_PATTERNS:
    if pattern in user_code:
        print(f"SecurityError: Code contains blocked pattern '{{pattern}}'", file=sys.stderr)
        sys.exit(1)

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
