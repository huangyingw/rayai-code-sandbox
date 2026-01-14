# Code Executor Sandbox

A secure HTTP API for executing arbitrary Python code with real-time streaming output.

## Features

- **Docker container isolation** (MANDATORY - each task runs in isolated container)
- **Multi-layer security**: OS-level + Python-level restrictions
- **Resource limits**: CPU, memory, processes, files
- **Network isolation**: No network access in sandbox
- **Module whitelist**: Only safe modules allowed
- **Real-time streaming**: SSE-based output streaming
- **Rate limiting**: Token bucket algorithm per IP
- **Concurrency control**: Configurable max concurrent tasks

## Setup

### Requirements

- Python 3.10+
- Unix-like OS (Linux/macOS) for resource limits
- Docker (REQUIRED - application will not start without Docker)

### Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Build Docker sandbox image (REQUIRED)
docker build -t python-sandbox:latest -f Dockerfile.sandbox .
```

### Running the Server

```bash
# Start the server (Docker required)
python main.py

# Or with uvicorn directly
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Note: The server will fail to start if Docker is not available.

The API will be available at `http://localhost:8000`.

- API documentation: `http://localhost:8000/docs`
- Security info: `http://localhost:8000/info`

## API Usage

### Execute Code

```bash
curl -X POST http://localhost:8000/execute \
  -H "Content-Type: application/json" \
  -d '{"code": "print(\"hello world\")"}'
```

Response:
```json
{"task_id": "abc12345"}
```

### Get Task Result

```bash
curl http://localhost:8000/tasks/{task_id}
```

Response:
```json
{
  "task_id": "abc12345",
  "status": "completed",
  "stdout": "hello world\n",
  "stderr": "",
  "exit_code": 0,
  "error_message": null,
  "created_at": "2024-01-15T10:30:00",
  "started_at": "2024-01-15T10:30:00",
  "finished_at": "2024-01-15T10:30:01"
}
```

### Stream Output (SSE)

```bash
curl -N http://localhost:8000/tasks/{task_id}/stream
```

### Kill Task

```bash
curl -X DELETE http://localhost:8000/tasks/{task_id}
```

## Approach & Design Decisions

### Architecture (with Docker)

```
┌──────────────────────────────────────────────────────────────┐
│                      Host Server                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                   FastAPI Server                        │  │
│  │  POST /execute  │  GET /tasks/id  │  GET /tasks/stream  │  │
│  └────────────────────────┬───────────────────────────────┘  │
│                           │                                   │
│                           ▼                                   │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              SandboxExecutor / DockerExecutor           │  │
│  │  ┌─────────────────┐    ┌────────────────────────┐     │  │
│  │  │  TaskStorage    │    │   Config               │     │  │
│  │  │  (Abstract)     │    │   - ExecutorConfig     │     │  │
│  │  │  └─MemoryStorage│    │   - SecurityConfig     │     │  │
│  │  │  └─RedisStorage │    │   - ServerConfig       │     │  │
│  │  │    (future)     │    │                        │     │  │
│  │  └─────────────────┘    └────────────────────────┘     │  │
│  └────────────────────────┬───────────────────────────────┘  │
│                           │                                   │
│                           ▼                                   │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              Docker Container (per task)                │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │  Security Restrictions:                          │  │  │
│  │  │  • --network=none (no network)                   │  │  │
│  │  │  • --read-only (read-only filesystem)            │  │  │
│  │  │  • --cap-drop=ALL (no capabilities)              │  │  │
│  │  │  • --memory=128m (memory limit)                  │  │  │
│  │  │  • --pids-limit=50 (process limit)               │  │  │
│  │  │  • --user=65534 (nobody user)                    │  │  │
│  │  │  • seccomp profile (syscall filtering)           │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │  Python Sandbox (second layer):                  │  │  │
│  │  │  • Restricted builtins                           │  │  │
│  │  │  • Module whitelist                              │  │  │
│  │  │  • __class__ escape prevention                   │  │  │
│  │  │  • Resource limits (backup)                      │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### Project Structure

```
sandbox/
├── __init__.py           # Package initialization
├── config.py             # Configuration management (env vars)
├── models.py             # Data models (Task, TaskStatus)
├── logging.py            # Logging configuration
├── executor/
│   ├── __init__.py
│   ├── sandbox.py        # Main executor implementation
│   └── wrapper.py        # Sandbox wrapper script template
├── storage/
│   ├── __init__.py
│   ├── base.py           # Abstract storage interface
│   └── memory.py         # In-memory storage implementation
└── api/
    ├── __init__.py
    └── routes.py         # FastAPI routes

# Security-specific files
docker_executor.py        # Docker-based executor
Dockerfile.sandbox        # Hardened sandbox container
seccomp-profile.json      # Syscall filtering rules
security_tests.py         # Security test suite
```

### Configuration

Configuration via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `EXECUTOR_TIMEOUT` | 10 | Max execution time (seconds) |
| `EXECUTOR_MAX_MEMORY` | 128 | Max memory (MB) |
| `EXECUTOR_MAX_OUTPUT` | 1048576 | Max output size (bytes) |
| `EXECUTOR_MAX_CONCURRENT` | 10 | Max concurrent running tasks |
| `DOCKER_IMAGE` | python-sandbox:latest | Docker image for sandbox |
| `DOCKER_MEMORY_LIMIT` | 128m | Container memory limit |
| `DOCKER_CPU_LIMIT` | 1.0 | Container CPU limit |
| `DOCKER_PIDS_LIMIT` | 50 | Container process limit |
| `RATE_LIMIT_ENABLED` | true | Enable rate limiting |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | 60 | Max requests per minute per IP |
| `RATE_LIMIT_BURST_SIZE` | 10 | Allow burst of requests |
| `SERVER_HOST` | 0.0.0.0 | Server bind host |
| `SERVER_PORT` | 8000 | Server bind port |
| `LOG_LEVEL` | INFO | Logging level |
| `DEBUG` | false | Debug mode |

### Security Layers

#### Layer 1: Docker Container Isolation (MANDATORY)

| Security Feature | Implementation |
|------------------|----------------|
| Network isolation | `--network=none` |
| Filesystem isolation | `--read-only` + tmpfs |
| Capability dropping | `--cap-drop=ALL` |
| Resource limits | `--memory`, `--cpus`, `--pids-limit` |
| User namespace | `--user=65534:65534` (nobody) |
| Privilege escalation | `--security-opt=no-new-privileges` |
| Syscall filtering | `seccomp-profile.json` |

#### Layer 2: Python Sandbox

| Security Feature | Implementation |
|------------------|----------------|
| Restricted builtins | Remove `eval`, `exec`, `open`, `__import__`, etc. |
| Module whitelist | Only allow safe modules: `math`, `json`, `datetime`, etc. |
| Resource limits | `resource.setrlimit()` for CPU, memory, files |
| Process limits | `RLIMIT_NPROC=1` to prevent fork bombs |
| Attribute blocking | Block `__class__`, `__bases__`, `__mro__`, etc. |
| Code pattern scanning | Detect dangerous patterns before execution |

#### Allowed Modules (Whitelist)

```python
ALLOWED_MODULES = {
    'math', 'cmath', 'decimal', 'fractions', 'random', 'statistics',
    'itertools', 'functools', 'operator',
    'string', 'textwrap',
    'datetime', 'calendar', 'time',
    'collections', 'heapq', 'bisect', 'array',
    'copy', 'pprint',
    'enum', 'dataclasses',
    're', 'json',
}
```

### Security Coverage

| Attack Vector | Protection Mechanism |
|---------------|---------------------|
| Module import bypass | ✓ Module whitelist + Docker isolation |
| `__class__` escape | ✓ Pattern scanning + attribute blocking |
| Fork bomb | ✓ `--pids-limit` + seccomp syscall filter |
| Network access | ✓ `--network=none` (complete isolation) |
| File system access | ✓ `--read-only` filesystem |
| Memory exhaustion | ✓ `--memory` limit (Docker enforced) |
| Shell escape | ✓ Shells removed from container image |
| Privilege escalation | ✓ `--cap-drop=ALL` + `no-new-privileges` |
| Syscall attacks | ✓ Seccomp profile filtering |

### Robustness Features

1. **Concurrency Limiting**: Maximum 10 concurrent tasks (configurable)
   - Uses asyncio Semaphore for efficient queueing
   - Tasks wait for available slots or fail immediately

2. **Rate Limiting**: Token bucket algorithm per IP
   - 60 requests/minute default (configurable)
   - Burst allowance for legitimate traffic spikes
   - Returns `429 Too Many Requests` with `Retry-After` header

3. **Monitoring Endpoints**:
   - `GET /health` - Quick health check with concurrency status
   - `GET /status` - Detailed system status
   - `GET /info` - Security configuration info

### Trade-offs

| Decision | Pros | Cons |
|----------|------|------|
| Docker mandatory | Maximum security, defense in depth | Requires Docker installation (~100ms startup) |
| One container per task | Complete task isolation, no cross-contamination | Higher resource usage |
| Whitelist vs blocklist | More secure, explicit control | Less permissive, may need updates |
| In-memory task store | Simple, fast | Lost on restart, no persistence |
| SSE vs WebSocket | Simpler, HTTP-compatible | One-way only |

### What's NOT Implemented (production considerations)

1. **Persistent task storage** - Database for task history
2. **Authentication** - Control who can execute code
3. **gVisor/Firecracker** - Even stronger isolation
4. **Distributed execution** - Multi-node scaling

## Test Examples

See `test_examples.py` for detailed test cases with problematic code.

### Example 1: Fork Bomb (Resource Exhaustion)

```python
# Attempt to create infinite processes
import os
while True:
    os.fork()
```

**Result**: `ImportError: Import of 'os' is not allowed for security reasons`

### Example 2: Infinite Loop (CPU Exhaustion)

```python
# Infinite loop
while True:
    pass
```

**Result**: Task status `timeout`, killed after 10 seconds

### Example 3: Memory Bomb

```python
# Try to allocate huge memory
x = "A" * (1024 * 1024 * 1024)  # 1GB
```

**Result**: Process killed due to memory limit (128MB)

### Example 4: File System Access

```python
# Try to read system files
with open("/etc/passwd") as f:
    print(f.read())
```

**Result**: `NameError` - `open` is not defined (removed from builtins)

### Example 5: Network Access

```python
# Try to make HTTP request
import requests
requests.get("http://evil.com")
```

**Result**: `ImportError: Import of 'requests' is not allowed for security reasons`

### Example 6: Code Injection via eval

```python
# Try to use eval
eval("__import__('os').system('rm -rf /')")
```

**Result**: `NameError` - `eval` is not defined

### Example 7: Sandbox Escape Attempt

```python
# Try to access dangerous attributes
().__class__.__bases__[0].__subclasses__()
```

**Result**: `SecurityError: Code contains blocked pattern '__class__'`

### Example 8: Unicode Code

```python
# Unicode variable names and strings
变量 = "Hello, 世界! 🌍"
print(变量)
```

**Result**: Executes successfully, outputs `Hello, 世界! 🌍`

## Correctness & Robustness Features

### Code Validation
- **Syntax checking**: Code is compiled before execution to catch syntax errors early
- **Empty code detection**: Empty or whitespace-only code is rejected immediately
- **Code length limit**: Maximum 100,000 characters to prevent memory issues
- **UTF-8 validation**: Invalid encoding is rejected with clear error message

### Real-time Streaming
- **Unbuffered output**: Uses `-u` flag and `line_buffering=True` for immediate output
- **Line-by-line streaming**: Output is streamed as it's produced, not buffered

### Error Handling
- **Clear error messages**: Specific messages for RecursionError, MemoryError, etc.
- **Exit code interpretation**: Proper handling of signal-based exits (SIGKILL, SIGXCPU)
- **Exception propagation**: User exceptions are captured and reported clearly

### Unicode Support
- **Full Unicode support**: Handles international characters, emojis, etc.
- **UTF-8 encoding**: All output is decoded as UTF-8 with error replacement

## Running Tests

```bash
# Run correctness tests
python test_correctness.py

# Run integration test examples
python test_examples.py

# Run security test suite (tests sandbox escapes)
python security_tests.py

# Run unit tests with pytest
pytest tests/ -v
```

### Security Test Categories

The `security_tests.py` includes tests for:

1. **Basic blocked operations** - `import os`, `open()`, `eval()`
2. **Class-based escapes** - `__class__.__bases__`, `__mro__`, `__globals__`
3. **Import bypasses** - `__import__`, `importlib`
4. **Resource exhaustion** - Fork bombs, memory bombs, infinite loops
5. **File system access** - Read/write files, path traversal
6. **Network access** - Sockets, HTTP requests, DNS
7. **Code injection** - `compile()`, pickle deserialization
