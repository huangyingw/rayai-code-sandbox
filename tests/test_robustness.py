#!/usr/bin/env python3
"""
Robustness Test Cases

Tests for edge cases, error handling, and problematic code.
"""

import asyncio
import pytest
from executor import CodeExecutor, TaskStatus


@pytest.fixture
def executor():
    """Create a code executor with short timeouts for testing."""
    return CodeExecutor(
        timeout=5,
        max_memory=64,
        max_output_size=1024 * 100,  # 100KB
        max_recursion_depth=50,
    )


class TestEdgeCases:
    """Tests for edge cases in input handling."""

    @pytest.mark.asyncio
    async def test_empty_code(self, executor):
        """Empty code should fail with validation error."""
        task_id = executor.create_task("")
        result = await executor.execute(task_id, "")

        assert result.status == TaskStatus.FAILED
        assert "Empty code" in result.error_message
        assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_whitespace_only_code(self, executor):
        """Whitespace-only code should fail with validation error."""
        task_id = executor.create_task("   \n\t\n   ")
        result = await executor.execute(task_id, "   \n\t\n   ")

        assert result.status == TaskStatus.FAILED
        assert "Empty code" in result.error_message
        assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_unicode_code(self, executor):
        """Unicode characters in code should work correctly."""
        code = 'print("Hello, 世界! 🌍")'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.COMPLETED
        assert "世界" in result.stdout
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_unicode_variable_names(self, executor):
        """Unicode variable names should work."""
        code = '变量 = 42\nprint(变量)'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.COMPLETED
        assert "42" in result.stdout

    @pytest.mark.asyncio
    async def test_multiline_code(self, executor):
        """Multiline code should execute correctly."""
        code = '''
def greet(name):
    return f"Hello, {name}!"

result = greet("World")
print(result)
'''
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.COMPLETED
        assert "Hello, World!" in result.stdout


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_syntax_error(self, executor):
        """Syntax errors should be caught and reported."""
        code = 'def broken(\n    print("missing paren"'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.FAILED
        assert result.exit_code != 0
        assert "SyntaxError" in result.stderr or "SyntaxError" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_name_error(self, executor):
        """NameError should be caught and reported."""
        code = 'print(undefined_variable)'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.FAILED
        assert "NameError" in result.stderr

    @pytest.mark.asyncio
    async def test_type_error(self, executor):
        """TypeError should be caught and reported."""
        code = '"string" + 42'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.FAILED
        assert "TypeError" in result.stderr

    @pytest.mark.asyncio
    async def test_zero_division(self, executor):
        """ZeroDivisionError should be caught and reported."""
        code = '1 / 0'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.FAILED
        assert "ZeroDivisionError" in result.stderr

    @pytest.mark.asyncio
    async def test_index_error(self, executor):
        """IndexError should be caught and reported."""
        code = '[1, 2, 3][10]'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.FAILED
        assert "IndexError" in result.stderr

    @pytest.mark.asyncio
    async def test_key_error(self, executor):
        """KeyError should be caught and reported."""
        code = '{"a": 1}["b"]'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.FAILED
        assert "KeyError" in result.stderr


class TestResourceLimits:
    """Tests for resource limit handling."""

    @pytest.mark.asyncio
    async def test_infinite_loop_timeout(self, executor):
        """Infinite loops should be terminated by timeout."""
        code = 'while True: pass'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status in (TaskStatus.TIMEOUT, TaskStatus.KILLED)

    @pytest.mark.asyncio
    async def test_recursion_limit(self, executor):
        """Deep recursion should be caught."""
        code = '''
def recurse(n):
    return recurse(n + 1)
recurse(0)
'''
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.FAILED
        assert "RecursionError" in result.stderr or "maximum recursion" in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_large_output_truncation(self, executor):
        """Large output should be truncated."""
        code = '''
for i in range(100000):
    print("A" * 100)
'''
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        # Should either complete with truncated output or timeout
        assert len(result.stdout) <= executor.max_output_size + 100  # Allow some buffer

    @pytest.mark.asyncio
    async def test_cpu_intensive_timeout(self, executor):
        """CPU-intensive operations should timeout."""
        code = '''
def fib(n):
    if n <= 1:
        return n
    return fib(n-1) + fib(n-2)
fib(100)  # This will take too long
'''
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status in (TaskStatus.TIMEOUT, TaskStatus.FAILED)


class TestSpecialCases:
    """Tests for special code patterns."""

    @pytest.mark.asyncio
    async def test_sys_exit_zero(self, executor):
        """SystemExit(0) should complete successfully."""
        code = 'raise SystemExit(0)'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.COMPLETED
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_sys_exit_nonzero(self, executor):
        """sys.exit with non-zero should fail."""
        code = 'raise SystemExit(1)'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.FAILED
        assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_print_to_stderr(self, executor):
        """Printing to stderr should be captured."""
        code = 'import sys; sys.stderr.write("error message\\n")'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        # sys is blocked, so this should fail
        assert result.status == TaskStatus.FAILED
        assert "Import" in result.stderr

    @pytest.mark.asyncio
    async def test_multiple_prints(self, executor):
        """Multiple print statements should all be captured."""
        code = '''
for i in range(5):
    print(f"Line {i}")
'''
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.COMPLETED
        for i in range(5):
            assert f"Line {i}" in result.stdout

    @pytest.mark.asyncio
    async def test_exception_with_message(self, executor):
        """Custom exception messages should be captured."""
        code = 'raise ValueError("Custom error message")'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.FAILED
        assert "Custom error message" in result.stderr


class TestValidCode:
    """Tests for valid code execution."""

    @pytest.mark.asyncio
    async def test_basic_math(self, executor):
        """Basic math operations should work."""
        code = 'print(2 + 2 * 3)'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.COMPLETED
        assert "8" in result.stdout

    @pytest.mark.asyncio
    async def test_list_comprehension(self, executor):
        """List comprehensions should work."""
        code = 'print([x**2 for x in range(5)])'
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.COMPLETED
        assert "[0, 1, 4, 9, 16]" in result.stdout

    @pytest.mark.asyncio
    async def test_dict_operations(self, executor):
        """Dictionary operations should work."""
        code = '''
d = {"a": 1, "b": 2}
d["c"] = 3
print(sorted(d.items()))
'''
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.COMPLETED
        assert "a" in result.stdout and "b" in result.stdout and "c" in result.stdout

    @pytest.mark.asyncio
    async def test_string_operations(self, executor):
        """String operations should work."""
        code = '''
s = "hello world"
print(s.upper())
print(s.split())
print(len(s))
'''
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.COMPLETED
        assert "HELLO WORLD" in result.stdout
        assert "11" in result.stdout

    @pytest.mark.asyncio
    async def test_safe_module_math(self, executor):
        """Safe modules like math should work."""
        code = '''
import math
print(round(math.pi, 4))
print(math.sqrt(16))
'''
        task_id = executor.create_task(code)
        result = await executor.execute(task_id, code)

        assert result.status == TaskStatus.COMPLETED
        assert "3.1416" in result.stdout
        assert "4.0" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
