#!/usr/bin/env python3
"""
Correctness Test Cases for Code Executor Sandbox

This file tests that valid code executes correctly and produces expected output.
Run with: python test_correctness.py
"""

import asyncio
import httpx


BASE_URL = "http://localhost:8000"


async def test_code(name: str, code: str, expected_status: str, expected_output: str = None):
    """Submit code and verify results."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")
    print(f"Code:\n{code}")
    print("-" * 60)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Submit code
        response = await client.post(
            f"{BASE_URL}/execute",
            json={"code": code}
        )

        if response.status_code != 200:
            print(f"FAILED: API returned {response.status_code}")
            print(f"Response: {response.text}")
            return False

        task_id = response.json()["task_id"]
        print(f"Task ID: {task_id}")

        # Wait for completion
        for _ in range(30):
            response = await client.get(f"{BASE_URL}/tasks/{task_id}")
            result = response.json()
            if result["status"] not in ("pending", "running"):
                break
            await asyncio.sleep(0.5)

        print(f"\nResult:")
        print(f"  Status: {result['status']}")
        print(f"  Stdout: {result['stdout'][:200] if result['stdout'] else '(empty)'}")
        if result["stderr"]:
            print(f"  Stderr: {result['stderr'][:200]}")
        if result["error_message"]:
            print(f"  Error: {result['error_message']}")

        # Verify status
        if result["status"] != expected_status:
            print(f"\n❌ FAILED: Expected status '{expected_status}', got '{result['status']}'")
            return False

        # Verify output if provided
        if expected_output is not None:
            if expected_output not in result["stdout"]:
                print(f"\n❌ FAILED: Expected output '{expected_output}' not found")
                return False

        print(f"\n✅ PASSED")
        return True


async def run_tests():
    """Run all correctness tests."""
    print("\n" + "=" * 60)
    print("CODE EXECUTOR SANDBOX - CORRECTNESS TESTS")
    print("=" * 60)
    print("\nMake sure the server is running: python main.py")

    results = []

    # Test 1: Basic print
    results.append(await test_code(
        "Basic print statement",
        'print("Hello, World!")',
        "completed",
        "Hello, World!"
    ))

    # Test 2: Arithmetic operations
    results.append(await test_code(
        "Arithmetic operations",
        '''
result = (10 + 20) * 3 - 15 / 5
print(f"Result: {result}")
''',
        "completed",
        "Result: 87.0"
    ))

    # Test 3: Loop with output
    results.append(await test_code(
        "For loop with output",
        '''
for i in range(5):
    print(f"Count: {i}")
''',
        "completed",
        "Count: 4"
    ))

    # Test 4: Function definition and call
    results.append(await test_code(
        "Function definition and call",
        '''
def greet(name):
    return f"Hello, {name}!"

print(greet("Python"))
''',
        "completed",
        "Hello, Python!"
    ))

    # Test 5: List comprehension
    results.append(await test_code(
        "List comprehension",
        '''
squares = [x**2 for x in range(10)]
print(squares)
''',
        "completed",
        "[0, 1, 4, 9, 16, 25, 36, 49, 64, 81]"
    ))

    # Test 6: Dictionary operations
    results.append(await test_code(
        "Dictionary operations",
        '''
data = {"a": 1, "b": 2, "c": 3}
data["d"] = 4
print(sorted(data.items()))
''',
        "completed",
        "[('a', 1), ('b', 2), ('c', 3), ('d', 4)]"
    ))

    # Test 7: Exception handling in user code
    results.append(await test_code(
        "Exception handling in user code",
        '''
try:
    x = 1 / 0
except ZeroDivisionError:
    print("Caught division by zero!")
''',
        "completed",
        "Caught division by zero!"
    ))

    # Test 8: Unicode support
    results.append(await test_code(
        "Unicode characters",
        '''
print("Hello 世界! 🎉")
print("Привет мир!")
''',
        "completed",
        "Hello 世界!"
    ))

    # Test 9: Safe math module
    results.append(await test_code(
        "Math module usage",
        '''
import math
print(f"Pi: {math.pi:.4f}")
print(f"sqrt(2): {math.sqrt(2):.4f}")
''',
        "completed",
        "Pi: 3.1416"
    ))

    # Test 10: Collections module
    results.append(await test_code(
        "Collections module usage",
        '''
from collections import Counter
words = ["apple", "banana", "apple", "cherry"]
print(Counter(words))
''',
        "completed",
        "Counter({'apple': 2"
    ))

    # Test 11: Class definition
    results.append(await test_code(
        "Class definition and instantiation",
        '''
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __repr__(self):
        return f"Point({self.x}, {self.y})"

p = Point(3, 4)
print(p)
''',
        "completed",
        "Point(3, 4)"
    ))

    # Test 12: Generator
    results.append(await test_code(
        "Generator function",
        '''
def fib_gen(n):
    a, b = 0, 1
    for _ in range(n):
        yield a
        a, b = b, a + b

print(list(fib_gen(10)))
''',
        "completed",
        "[0, 1, 1, 2, 3, 5, 8, 13, 21, 34]"
    ))

    # Test 13: Recursion (within limit)
    results.append(await test_code(
        "Recursion within limit",
        '''
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

print(f"5! = {factorial(5)}")
''',
        "completed",
        "5! = 120"
    ))

    # Test 14: Deep recursion (should fail)
    results.append(await test_code(
        "Deep recursion (should fail)",
        '''
def deep_recursion(n):
    return deep_recursion(n + 1)

deep_recursion(0)
''',
        "failed",
        None
    ))

    # Test 15: Syntax error
    results.append(await test_code(
        "Syntax error detection",
        '''
def broken(
    print("missing paren")
''',
        "failed",
        None
    ))

    # Test 16: Multiple outputs (streaming test)
    results.append(await test_code(
        "Multiple outputs for streaming",
        '''
import time
for i in range(5):
    print(f"Line {i}")
''',
        "completed",
        "Line 4"
    ))

    # Test 17: Lambda functions
    results.append(await test_code(
        "Lambda functions",
        '''
square = lambda x: x ** 2
numbers = [1, 2, 3, 4, 5]
print(list(map(square, numbers)))
''',
        "completed",
        "[1, 4, 9, 16, 25]"
    ))

    # Test 18: String operations
    results.append(await test_code(
        "String operations",
        '''
s = "Hello, World!"
print(s.upper())
print(s.split(", "))
print(s[::-1])
''',
        "completed",
        "HELLO, WORLD!"
    ))

    # Test 19: Async/await with user-managed asyncio.run
    results.append(await test_code(
        "Async/await with asyncio.run",
        '''
import asyncio

async def hello():
    await asyncio.sleep(0.1)
    print("Hello from async!")

asyncio.run(hello())
''',
        "completed",
        "Hello from async!"
    ))

    # Test 20: Top-level await
    results.append(await test_code(
        "Top-level await",
        '''
import asyncio
await asyncio.sleep(0.1)
print("Done with top-level await!")
''',
        "completed",
        "Done with top-level await!"
    ))

    # Test 21: __future__ imports
    results.append(await test_code(
        "__future__ imports",
        '''
from __future__ import annotations

def greet(name: str) -> str:
    return f"Hello, {name}!"

print(greet("Future"))
''',
        "completed",
        "Hello, Future!"
    ))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    if passed == total:
        print("✅ All tests passed!")
    else:
        print(f"❌ {total - passed} test(s) failed")


if __name__ == "__main__":
    asyncio.run(run_tests())
