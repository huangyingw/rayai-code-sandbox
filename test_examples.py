#!/usr/bin/env python3
"""
Test Examples for Code Executor Sandbox

This file contains examples of problematic code and how the sandbox handles them.
Run with: python test_examples.py
"""

import asyncio
import time
import httpx


BASE_URL = "http://localhost:8000"


async def test_code(name: str, code: str, expected_behavior: str):
    """Submit code and display results."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")
    print(f"Code:\n{code}")
    print(f"\nExpected: {expected_behavior}")
    print("-" * 60)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Submit code
        response = await client.post(
            f"{BASE_URL}/execute",
            json={"code": code}
        )

        # Handle error responses (e.g., rate limiting)
        if response.status_code != 200:
            print(f"\nResult:")
            print(f"  HTTP Error: {response.status_code}")
            error_data = response.json()
            print(f"  Detail: {error_data.get('detail', 'Unknown error')}")
            return

        task_id = response.json()["task_id"]
        print(f"Task ID: {task_id}")

        # Wait for completion
        result = None
        for _ in range(30):  # Max 30 seconds
            response = await client.get(f"{BASE_URL}/tasks/{task_id}")
            if response.status_code != 200:
                print(f"\nResult:")
                print(f"  HTTP Error: {response.status_code}")
                return
            result = response.json()
            if result["status"] not in ("pending", "running"):
                break
            await asyncio.sleep(1)

        print(f"\nResult:")
        print(f"  Status: {result['status']}")
        if result.get("stdout"):
            print(f"  Stdout: {result['stdout'][:200]}...")
        if result.get("stderr"):
            print(f"  Stderr: {result['stderr'][:200]}...")
        if result.get("error_message"):
            print(f"  Error: {result['error_message']}")
        print(f"  Exit Code: {result.get('exit_code')}")


async def run_tests():
    """Run all test cases."""
    print("\n" + "=" * 60)
    print("CODE EXECUTOR SANDBOX - TEST EXAMPLES")
    print("=" * 60)
    print("\nMake sure the server is running: python main.py")
    print("Press Ctrl+C to stop\n")

    # Delay between tests to avoid rate limiting
    test_delay = 2.0  # seconds

    # Test 1: Valid code
    await test_code(
        "Valid Code - Hello World",
        'print("Hello, World!")',
        "Should execute successfully and print output"
    )
    await asyncio.sleep(test_delay)

    # Test 2: Valid code with loop
    await test_code(
        "Valid Code - Loop",
        '''
for i in range(5):
    print(f"Count: {i}")
''',
        "Should execute successfully and print 0-4"
    )
    await asyncio.sleep(test_delay)

    # Test 3: Fork bomb attempt
    await test_code(
        "MALICIOUS: Fork Bomb",
        '''
import os
while True:
    os.fork()
''',
        "Should BLOCK: os module is not allowed"
    )
    await asyncio.sleep(test_delay)

    # Test 4: Infinite loop
    await test_code(
        "PROBLEMATIC: Infinite Loop",
        '''
while True:
    pass
''',
        "Should TIMEOUT: killed after 10 seconds"
    )
    await asyncio.sleep(test_delay)

    # Test 5: Memory bomb
    await test_code(
        "MALICIOUS: Memory Exhaustion",
        '''
# Try to allocate 1GB
x = []
for i in range(1024 * 1024 * 100):
    x.append("A" * 1024)
''',
        "Should KILL: process killed due to memory limit"
    )
    await asyncio.sleep(test_delay)

    # Test 6: File system access
    await test_code(
        "MALICIOUS: File System Access",
        '''
with open("/etc/passwd", "r") as f:
    print(f.read())
''',
        "Should BLOCK: open() is not defined"
    )
    await asyncio.sleep(test_delay)

    # Test 7: Network access
    await test_code(
        "MALICIOUS: Network Access (socket)",
        '''
import socket
s = socket.socket()
s.connect(("google.com", 80))
''',
        "Should BLOCK: socket module is not allowed"
    )
    await asyncio.sleep(test_delay)

    # Test 8: Subprocess execution
    await test_code(
        "MALICIOUS: Shell Command Execution",
        '''
import subprocess
subprocess.run(["ls", "-la", "/"])
''',
        "Should BLOCK: subprocess module is not allowed"
    )
    await asyncio.sleep(test_delay)

    # Test 9: eval/exec
    await test_code(
        "MALICIOUS: Dynamic Code Execution",
        '''
eval("print('pwned')")
''',
        "Should BLOCK: eval() is not defined"
    )
    await asyncio.sleep(test_delay)

    # Test 10: Import bypass attempt
    await test_code(
        "MALICIOUS: Import Bypass via __import__",
        '''
os = __import__('os')
os.system('whoami')
''',
        "Should BLOCK: os import is blocked"
    )
    await asyncio.sleep(test_delay)

    # Test 11: Builtins manipulation
    await test_code(
        "MALICIOUS: Builtins Access",
        '''
import builtins
builtins.open("/etc/passwd")
''',
        "Should BLOCK: builtins module is not allowed"
    )
    await asyncio.sleep(test_delay)

    # Test 12: Exception with stack trace
    await test_code(
        "PROBLEMATIC: Unhandled Exception",
        '''
def foo():
    return bar()

def bar():
    raise ValueError("Something went wrong!")

foo()
''',
        "Should FAIL: with error message"
    )
    await asyncio.sleep(test_delay)

    # Test 13: Syntax error
    await test_code(
        "BUGGY: Syntax Error",
        '''
def broken(
    print("missing paren")
''',
        "Should FAIL: syntax error"
    )
    await asyncio.sleep(test_delay)

    # Test 14: Large output
    await test_code(
        "PROBLEMATIC: Large Output",
        '''
for i in range(100000):
    print("A" * 100)
''',
        "Should TRUNCATE: output limited to 1MB"
    )
    await asyncio.sleep(test_delay)

    # Test 15: CPU-intensive computation
    await test_code(
        "PROBLEMATIC: CPU Intensive",
        '''
# Compute fibonacci recursively (slow)
def fib(n):
    if n <= 1:
        return n
    return fib(n-1) + fib(n-2)

print(fib(35))
''',
        "May TIMEOUT or complete depending on system"
    )
    await asyncio.sleep(test_delay)

    # Test 16: Safe math operations
    await test_code(
        "Valid Code - Math",
        '''
import math
print(f"Pi: {math.pi}")
print(f"sqrt(2): {math.sqrt(2)}")
print(f"sin(0): {math.sin(0)}")
''',
        "Should SUCCEED: math module is allowed"
    )
    await asyncio.sleep(test_delay)

    # Test 17: Safe data structures
    await test_code(
        "Valid Code - Collections",
        '''
from collections import Counter, defaultdict

words = ["apple", "banana", "apple", "cherry", "banana", "apple"]
counter = Counter(words)
print(f"Word counts: {counter}")

dd = defaultdict(list)
dd["fruits"].append("apple")
print(f"Default dict: {dict(dd)}")
''',
        "Should SUCCEED: collections module is allowed"
    )

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
