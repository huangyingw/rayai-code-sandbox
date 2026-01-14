"""
Sandbox wrapper script template.

This module contains the unified template for the sandboxed execution environment
with enhanced security measures to prevent sandbox escapes.

Used by both Docker and subprocess execution modes.
"""

# The wrapper script that sets up resource limits and restricted execution
SANDBOX_WRAPPER_TEMPLATE = '''
import sys
import resource
import signal
import builtins

# Force unbuffered output for real-time streaming
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Set resource limits (but NOT recursion limit yet - need to import modules first)
MAX_CPU_TIME = {cpu_time}  # seconds
MAX_MEMORY = {memory} * 1024 * 1024  # bytes
MAX_FILE_SIZE = 1024 * 1024  # 1MB
MAX_OPEN_FILES = 10
MAX_RECURSION_DEPTH = {recursion_limit}  # Recursion limit for user code

try:
    resource.setrlimit(resource.RLIMIT_CPU, (MAX_CPU_TIME, MAX_CPU_TIME))
    resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY, MAX_MEMORY))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_SIZE, MAX_FILE_SIZE))
    resource.setrlimit(resource.RLIMIT_NOFILE, (MAX_OPEN_FILES, MAX_OPEN_FILES))
    # Prevent fork bombs (may not be available on all systems)
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
    except (AttributeError, ValueError):
        pass
except (ValueError, resource.error):
    pass  # Some limits may not be available on all systems

# Set up signal handler for CPU time limit
def timeout_handler(signum, frame):
    print("Error: CPU time limit exceeded", file=sys.stderr)
    sys.exit(137)

signal.signal(signal.SIGXCPU, timeout_handler)

# =============================================================================
# Import required modules BEFORE setting recursion limit
# =============================================================================
import asyncio
import ast

# =============================================================================
# Now set recursion limit (after all internal imports are done)
# =============================================================================
sys.setrecursionlimit(MAX_RECURSION_DEPTH)

# =============================================================================
# SECURITY: Scan code for dangerous patterns before execution
# =============================================================================
DANGEROUS_PATTERNS = [
    '__class__', '__bases__', '__mro__', '__subclasses__',
    '__globals__', '__code__', '__builtins__',
]

user_code = {user_code!r}

for pattern in DANGEROUS_PATTERNS:
    if pattern in user_code:
        print(f"SecurityError: Code contains blocked pattern '{{pattern}}'", file=sys.stderr)
        sys.exit(1)

# =============================================================================
# Restricted builtins
# =============================================================================
_safe_builtins = {{
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
    'tuple': tuple, 'type': type, 'zip': zip,
    'True': True, 'False': False, 'None': None,
    # Safe getattr/hasattr
    'getattr': getattr,
    'hasattr': hasattr,
    # Safe exceptions
    'Exception': Exception, 'BaseException': BaseException,
    'ValueError': ValueError, 'TypeError': TypeError,
    'KeyError': KeyError, 'IndexError': IndexError,
    'AttributeError': AttributeError, 'RuntimeError': RuntimeError,
    'StopIteration': StopIteration, 'ZeroDivisionError': ZeroDivisionError,
    'SystemExit': SystemExit, 'RecursionError': RecursionError,
    'MemoryError': MemoryError, 'OverflowError': OverflowError,
    'ArithmeticError': ArithmeticError, 'LookupError': LookupError,
    'AssertionError': AssertionError, 'NotImplementedError': NotImplementedError,
    'NameError': NameError, 'ImportError': ImportError,
    # Required for class definitions
    '__build_class__': __build_class__,
}}

# Create restricted __builtins__
restricted_builtins = dict(_safe_builtins)

# =============================================================================
# Custom import function - whitelist approach for better security
# =============================================================================
_original_import = builtins.__import__
ALLOWED_MODULES = {allowed_modules}

def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    base_module = name.split('.')[0]
    if base_module not in ALLOWED_MODULES:
        raise ImportError(f"Module '{{name}}' is not allowed. Allowed modules: {{sorted(ALLOWED_MODULES)}}")
    return _original_import(name, globals, locals, fromlist, level)

restricted_builtins['__import__'] = _restricted_import

# =============================================================================
# Handle async/await and __future__ imports
# =============================================================================
def _has_top_level_await(code):
    """Detect if code has top-level await (not inside async function)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Await):
            if node in tree.body:
                return True
    return False

def _wrap_for_top_level_await(code):
    """Wrap code with top-level await to run with asyncio."""
    lines = code.split('\\n')
    indented_lines = []
    for line in lines:
        if line.strip():
            indented_lines.append('    ' + line)
        else:
            indented_lines.append(line)
    indented = '\\n'.join(indented_lines)
    return f"async def __async_main__():\\n{{indented}}\\nimport asyncio\\nasyncio.run(__async_main__())"

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
            names = ', '.join(alias.name for alias in node.names)
            future_imports.append(f"from __future__ import {{names}}")
            first_non_future_idx = i + 1
        elif isinstance(node, (ast.Expr, ast.Pass)) and isinstance(getattr(node, 'value', None), ast.Constant):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                first_non_future_idx = i + 1
                continue
            break
        else:
            break

    if not future_imports:
        return "", code

    lines = code.split('\\n')
    if first_non_future_idx < len(tree.body):
        first_real_line = tree.body[first_non_future_idx].lineno - 1
        remaining = '\\n'.join(lines[first_real_line:])
    else:
        remaining = ""

    return '\\n'.join(future_imports), remaining

# =============================================================================
# Execute user code
# =============================================================================
try:
    # Extract and handle __future__ imports
    future_imports, remaining_code = _extract_future_imports(user_code)

    # Build execution namespace
    exec_globals = {{'__builtins__': restricted_builtins, '__name__': '__main__', '__doc__': None}}

    # Execute __future__ imports first (they need real builtins temporarily)
    if future_imports:
        exec(future_imports, {{'__builtins__': builtins}})

    # Handle top-level await by wrapping in async function
    if _has_top_level_await(remaining_code):
        remaining_code = _wrap_for_top_level_await(remaining_code)

    # Compile first to catch syntax errors
    compiled = compile(remaining_code, '<user_code>', 'exec')

    # Execute the main code
    exec(compiled, exec_globals)
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
    allowed_modules: list[str],
) -> str:
    """Generate the sandbox wrapper script with the given parameters.

    This is the unified wrapper used by both Docker and subprocess execution.

    Args:
        code: User code to execute
        cpu_time: Max CPU time in seconds
        memory: Max memory in MB
        recursion_limit: Max recursion depth
        allowed_modules: List of modules allowed for import (whitelist)

    Returns:
        Complete wrapper script as string
    """
    return SANDBOX_WRAPPER_TEMPLATE.format(
        cpu_time=cpu_time,
        memory=memory,
        recursion_limit=recursion_limit,
        allowed_modules=repr(set(allowed_modules)),
        user_code=code,
    )
