"""
Configuration management for the sandbox.

Supports environment variables and sensible defaults.
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class ExecutorConfig:
    """Configuration for code execution."""
    timeout: int = 10  # seconds
    max_memory: int = 128  # MB
    max_output_size: int = 1024 * 1024  # 1MB
    max_code_size: int = 100000  # characters
    recursion_limit: int = 100  # max recursion depth to prevent stack overflow
    max_concurrent_tasks: int = 10  # max number of tasks running simultaneously


@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""
    enabled: bool = True
    requests_per_minute: int = 60  # max requests per minute per IP
    burst_size: int = 10  # allow burst of requests


@dataclass
class SecurityConfig:
    """Security-related configuration."""
    use_docker: str = "auto"  # "true", "false", or "auto"
    blocked_modules: List[str] = field(default_factory=lambda: [
        "os", "subprocess", "shutil", "sys", "importlib",
        "ctypes", "multiprocessing", "threading", "socket",
        "http", "urllib", "requests", "ftplib", "smtplib",
        "pickle", "marshal", "shelve", "dbm",
        "code", "codeop", "compile", "exec", "eval",
        "builtins", "__builtins__",
        "pty", "tty", "termios", "fcntl",
        "resource", "signal", "gc",
        "ast", "dis", "inspect", "traceback",
    ])
    # Modules allowed for import (whitelist - used when Docker is enabled)
    allowed_modules: List[str] = field(default_factory=lambda: [
        'math', 'cmath', 'decimal', 'fractions', 'random', 'statistics',
        'itertools', 'functools', 'operator',
        'string', 'textwrap',
        'datetime', 'calendar', 'time',
        'collections', 'heapq', 'bisect', 'array',
        'copy', 'pprint',
        'enum', 'dataclasses',
        're', 'json',
    ])


@dataclass
class ServerConfig:
    """Server configuration."""
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"


@dataclass
class Config:
    """Main configuration container."""
    executor: ExecutorConfig = field(default_factory=ExecutorConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)


def load_config() -> Config:
    """Load configuration from environment variables."""
    config = Config()

    # Executor settings
    if timeout := os.getenv("EXECUTOR_TIMEOUT"):
        config.executor.timeout = int(timeout)
    if max_memory := os.getenv("EXECUTOR_MAX_MEMORY"):
        config.executor.max_memory = int(max_memory)
    if max_output := os.getenv("EXECUTOR_MAX_OUTPUT"):
        config.executor.max_output_size = int(max_output)
    if recursion_limit := os.getenv("EXECUTOR_RECURSION_LIMIT"):
        config.executor.recursion_limit = int(recursion_limit)
    if max_concurrent := os.getenv("EXECUTOR_MAX_CONCURRENT"):
        config.executor.max_concurrent_tasks = int(max_concurrent)

    # Rate limit settings
    if rate_limit_enabled := os.getenv("RATE_LIMIT_ENABLED"):
        config.rate_limit.enabled = rate_limit_enabled.lower() in ("true", "1", "yes")
    if requests_per_minute := os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE"):
        config.rate_limit.requests_per_minute = int(requests_per_minute)
    if burst_size := os.getenv("RATE_LIMIT_BURST_SIZE"):
        config.rate_limit.burst_size = int(burst_size)

    # Security settings
    if use_docker := os.getenv("USE_DOCKER"):
        config.security.use_docker = use_docker.lower()

    # Server settings
    if host := os.getenv("SERVER_HOST"):
        config.server.host = host
    if port := os.getenv("SERVER_PORT"):
        config.server.port = int(port)
    if debug := os.getenv("DEBUG"):
        config.server.debug = debug.lower() in ("true", "1", "yes")
    if log_level := os.getenv("LOG_LEVEL"):
        config.server.log_level = log_level.upper()

    return config


# Global config instance
config = load_config()
