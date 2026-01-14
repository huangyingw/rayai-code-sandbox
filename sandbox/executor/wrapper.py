"""
Sandbox wrapper script template.

This module contains the template for the sandboxed execution environment.
"""

# The wrapper script that sets up resource limits and restricted execution
SANDBOX_WRAPPER_TEMPLATE = '''
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


def generate_wrapper(
    code: str,
    cpu_time: int,
    memory: int,
    blocked_modules: list[str]
) -> str:
    """Generate the sandbox wrapper script with the given parameters."""
    return SANDBOX_WRAPPER_TEMPLATE.format(
        cpu_time=cpu_time,
        memory=memory,
        blocked_modules=repr(blocked_modules),
        user_code=code,
    )
