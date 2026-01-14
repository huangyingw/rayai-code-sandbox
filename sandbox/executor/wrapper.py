"""
Sandbox wrapper script template.

This module contains the template for the sandboxed execution environment.
"""

# The wrapper script that sets up resource limits and restricted execution
SANDBOX_WRAPPER_TEMPLATE = '''
import sys
import resource
import signal

# Force unbuffered output for real-time streaming
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Set resource limits
MAX_CPU_TIME = {cpu_time}  # seconds
MAX_MEMORY = {memory} * 1024 * 1024  # bytes
MAX_FILE_SIZE = 1024 * 1024  # 1MB
MAX_OPEN_FILES = 10
MAX_RECURSION_DEPTH = {recursion_limit}  # Recursion limit

try:
    resource.setrlimit(resource.RLIMIT_CPU, (MAX_CPU_TIME, MAX_CPU_TIME))
    resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY, MAX_MEMORY))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_SIZE, MAX_FILE_SIZE))
    resource.setrlimit(resource.RLIMIT_NOFILE, (MAX_OPEN_FILES, MAX_OPEN_FILES))
except (ValueError, resource.error):
    pass  # Some limits may not be available on all systems

# Set recursion limit to prevent stack overflow
sys.setrecursionlimit(MAX_RECURSION_DEPTH)

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
    'SystemExit': SystemExit, 'RecursionError': RecursionError,
    'MemoryError': MemoryError, 'OverflowError': OverflowError,
    'ArithmeticError': ArithmeticError, 'LookupError': LookupError,
    'AssertionError': AssertionError, 'NotImplementedError': NotImplementedError,
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

# Check if code contains async/await patterns
import asyncio
import ast as _ast

def _has_top_level_await(code):
    """Detect if code has top-level await (not inside async function)."""
    try:
        tree = _ast.parse(code)
    except SyntaxError:
        return False

    # Check for Await nodes at module level (not inside async functions)
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Expr) and isinstance(node.value, _ast.Await):
            # Check if this is at module level by seeing if it's a direct child
            if node in tree.body:
                return True
    return False

def _wrap_for_top_level_await(code):
    """Wrap code with top-level await to run with asyncio."""
    # Indent all lines and wrap in async main
    lines = code.split('\\n')
    indented_lines = []
    for line in lines:
        if line.strip():
            indented_lines.append('    ' + line)
        else:
            indented_lines.append(line)
    indented = '\\n'.join(indented_lines)
    return f"async def __async_main__():\\n{{indented}}\\nimport asyncio\\nasyncio.run(__async_main__())"

# Handle __future__ imports - they must be at the beginning
import ast

def _extract_future_imports(code):
    """Extract __future__ imports and return (future_imports, remaining_code)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return "", code

    future_imports = []
    first_non_future_idx = 0

    for i, node in enumerate(tree.body):
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            # Reconstruct the import statement
            names = ', '.join(alias.name for alias in node.names)
            future_imports.append(f"from __future__ import {{names}}")
            first_non_future_idx = i + 1
        elif isinstance(node, (ast.Expr, ast.Pass)) and isinstance(getattr(node, 'value', None), ast.Constant):
            # Allow docstrings before __future__ imports
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                first_non_future_idx = i + 1
                continue
            break
        else:
            break

    if not future_imports:
        return "", code

    # Get the line numbers to split the code
    lines = code.split('\\n')
    if first_non_future_idx < len(tree.body):
        first_real_line = tree.body[first_non_future_idx].lineno - 1
        remaining = '\\n'.join(lines[first_real_line:])
    else:
        remaining = ""

    return '\\n'.join(future_imports), remaining

try:
    # Extract and handle __future__ imports
    future_imports, remaining_code = _extract_future_imports(user_code)

    # Build execution namespace
    exec_globals = {{'__builtins__': restricted_builtins, '__name__': '__main__'}}

    # Execute __future__ imports first (they need real builtins temporarily)
    if future_imports:
        exec(future_imports, {{'__builtins__': builtins}})

    # Handle top-level await by wrapping in async function
    if _has_top_level_await(remaining_code):
        remaining_code = _wrap_for_top_level_await(remaining_code)

    # Execute the main code
    exec(remaining_code, exec_globals)
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
    recursion_limit: int,
    blocked_modules: list[str]
) -> str:
    """Generate the sandbox wrapper script with the given parameters."""
    return SANDBOX_WRAPPER_TEMPLATE.format(
        cpu_time=cpu_time,
        memory=memory,
        recursion_limit=recursion_limit,
        blocked_modules=repr(blocked_modules),
        user_code=code,
    )
