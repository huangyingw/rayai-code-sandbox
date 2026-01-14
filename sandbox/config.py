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


@dataclass
class SecurityConfig:
    """Security-related configuration."""
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
