#!/usr/bin/env python3
"""
Security Test Cases for Code Executor Sandbox

This file contains various sandbox escape attempts and security tests.
All of these should be BLOCKED by the sandbox.
"""

# Test cases: (name, code, expected_to_be_blocked)
SECURITY_TEST_CASES = [
    # === Basic Blocked Operations ===
    (
        "Direct OS import",
        "import os; os.system('whoami')",
        True,
    ),
    (
        "Direct subprocess import",
        "import subprocess; subprocess.run(['ls'])",
        True,
    ),
    (
        "Direct socket import",
        "import socket; socket.socket()",
        True,
    ),
    (
        "Open file",
        "open('/etc/passwd').read()",
        True,
    ),
    (
        "Eval function",
        "eval('1+1')",
        True,
    ),
    (
        "Exec function",
        "exec('print(1)')",
        True,
    ),

    # === Class-based Escapes (Python sandbox bypass attempts) ===
    (
        "Escape via __class__.__bases__",
        """
# Attempt to access object base and find os module
x = ().__class__.__bases__[0].__subclasses__()
for c in x:
    if 'wrapper' in str(c):
        print(c)
""",
        True,
    ),
    (
        "Escape via __mro__",
        """
# Try to traverse method resolution order
''.__class__.__mro__[1].__subclasses__()
""",
        True,
    ),
    (
        "Escape via __globals__",
        """
# Try to access function globals
def f(): pass
f.__globals__['__builtins__']['eval']('1+1')
""",
        True,
    ),
    (
        "Escape via __code__",
        """
# Try to access code object
def f(): pass
f.__code__.co_consts
""",
        True,
    ),
    (
        "Escape via __builtins__ from function",
        """
def f():
    return __builtins__
print(f())
""",
        True,
    ),
    (
        "Escape via type()",
        """
# Create new type with __bases__
type('X', (object,), {'__init__': lambda s: None})
""",
        True,  # type() allows but doesn't provide access to dangerous attrs
    ),
    (
        "Escape via format string",
        """
# Format string attack
'{0.__class__.__mro__}'.format('')
""",
        True,
    ),
    (
        "Escape via getattr",
        """
# getattr to access private attributes
getattr(getattr('', '__class__'), '__bases__')
""",
        True,
    ),

    # === Import Bypasses ===
    (
        "Import via __import__",
        "__import__('os').system('id')",
        True,
    ),
    (
        "Import via importlib",
        "import importlib; importlib.import_module('os')",
        True,
    ),
    (
        "Import via __builtins__",
        "__builtins__.__import__('os')",
        True,
    ),

    # === Resource Exhaustion ===
    (
        "Fork bomb",
        """
import os
while True:
    os.fork()
""",
        True,  # os import blocked
    ),
    (
        "Memory bomb",
        """
x = []
while True:
    x.append('A' * 10**6)
""",
        True,  # Should be killed by memory limit
    ),
    (
        "CPU bomb (infinite loop)",
        """
while True:
    pass
""",
        True,  # Should timeout
    ),
    (
        "Recursive bomb",
        """
def f(): f()
f()
""",
        True,  # Should hit recursion limit
    ),

    # === File System Access ===
    (
        "Read /etc/passwd",
        "print(open('/etc/passwd').read())",
        True,
    ),
    (
        "Write to filesystem",
        "open('/tmp/hack', 'w').write('pwned')",
        True,
    ),
    (
        "List directory",
        "import os; print(os.listdir('/'))",
        True,
    ),
    (
        "Path traversal",
        "open('../../../etc/passwd').read()",
        True,
    ),

    # === Network Access ===
    (
        "HTTP request",
        "import urllib.request; urllib.request.urlopen('http://evil.com')",
        True,
    ),
    (
        "Socket connection",
        """
import socket
s = socket.socket()
s.connect(('8.8.8.8', 53))
""",
        True,
    ),
    (
        "DNS lookup",
        "import socket; socket.gethostbyname('google.com')",
        True,
    ),

    # === Code Injection ===
    (
        "Compile and exec",
        """
code = compile('import os', '<string>', 'exec')
exec(code)
""",
        True,
    ),
    (
        "Pickle deserialization attack",
        """
import pickle
class Exploit:
    def __reduce__(self):
        import os
        return (os.system, ('whoami',))
pickle.dumps(Exploit())
""",
        True,
    ),

    # === Valid Code (should work) ===
    (
        "Basic print",
        "print('Hello, World!')",
        False,
    ),
    (
        "Math operations",
        "import math; print(math.sqrt(16))",
        False,
    ),
    (
        "List comprehension",
        "print([x**2 for x in range(10)])",
        False,
    ),
    (
        "Function definition",
        """
def greet(name):
    return f'Hello, {name}!'
print(greet('World'))
""",
        False,
    ),
    (
        "Class definition",
        """
class Point:
    def __init__(self, x, y):
        self.x, self.y = x, y
    def __repr__(self):
        return f'Point({self.x}, {self.y})'
print(Point(3, 4))
""",
        False,
    ),
    (
        "JSON operations",
        """
import json
data = {'name': 'test', 'value': 42}
print(json.dumps(data))
""",
        False,
    ),
    (
        "Datetime operations",
        """
from datetime import datetime
print(datetime.now().isoformat())
""",
        False,
    ),
    (
        "Collections usage",
        """
from collections import Counter
words = ['a', 'b', 'a', 'c', 'a', 'b']
print(Counter(words))
""",
        False,
    ),
]


async def run_security_tests():
    """Run all security tests and report results."""
    import asyncio
    import httpx

    BASE_URL = "http://localhost:8000"

    print("=" * 70)
    print("SECURITY TEST SUITE")
    print("=" * 70)

    passed = 0
    failed = 0
    errors = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for name, code, should_block in SECURITY_TEST_CASES:
            print(f"\nTest: {name}")
            print(f"  Should be blocked: {should_block}")

            try:
                # Submit code
                resp = await client.post(
                    f"{BASE_URL}/execute",
                    json={"code": code}
                )
                task_id = resp.json()["task_id"]

                # Wait for result
                for _ in range(30):
                    resp = await client.get(f"{BASE_URL}/tasks/{task_id}")
                    result = resp.json()
                    if result["status"] not in ("pending", "running"):
                        break
                    await asyncio.sleep(0.5)

                # Check result
                is_blocked = result["status"] in ("failed", "timeout", "killed")

                if is_blocked == should_block:
                    print(f"  ✓ PASS - Status: {result['status']}")
                    passed += 1
                else:
                    print(f"  ✗ FAIL - Status: {result['status']}")
                    print(f"    Expected blocked={should_block}, got blocked={is_blocked}")
                    if result.get("stdout"):
                        print(f"    Stdout: {result['stdout'][:100]}")
                    if result.get("stderr"):
                        print(f"    Stderr: {result['stderr'][:100]}")
                    failed += 1
                    errors.append((name, result))

            except Exception as e:
                print(f"  ✗ ERROR: {e}")
                failed += 1
                errors.append((name, str(e)))

    # Summary
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    if errors:
        print("\nFailed tests:")
        for name, detail in errors:
            print(f"  - {name}")

    return failed == 0


if __name__ == "__main__":
    import asyncio
    print("Make sure the server is running: python main.py")
    print("Press Ctrl+C to stop\n")
    success = asyncio.run(run_security_tests())
    exit(0 if success else 1)
