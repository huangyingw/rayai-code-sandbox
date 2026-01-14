# Code Executor Sandbox

A secure HTTP API for executing arbitrary Python code with real-time streaming output.

## Features

- **Docker container isolation** (optional, recommended for production)
- **Multi-layer security**: OS-level + Python-level restrictions
- **Resource limits**: CPU, memory, processes, files
- **Network isolation**: No network access in sandbox
- **Module whitelist**: Only safe modules allowed
- **Real-time streaming**: SSE-based output streaming

## Setup

### Requirements

- Python 3.10+
- Unix-like OS (Linux/macOS) for resource limits
- Docker (optional, for enhanced security)

### Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# (Optional) Build Docker sandbox image for enhanced security
docker build -t python-sandbox:latest -f Dockerfile.sandbox .
```

### Running the Server

```bash
# Development (auto-detects Docker)
python main.py

# Force Docker mode
USE_DOCKER=true python main.py

# Force subprocess mode (no Docker)
USE_DOCKER=false python main.py

# Or with uvicorn directly
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

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
│  │                  DockerExecutor                         │  │
│  │  - Task management (in-memory store)                   │  │
│  │  - Output buffering for streaming                      │  │
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
│  │  └──────────────────────────────────────────────────┘  │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │  Python Sandbox (second layer):                  │  │  │
│  │  │  • Restricted builtins                           │  │  │
│  │  │  • Module whitelist                              │  │  │
│  │  │  • Resource limits (backup)                      │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### Security Layers

#### Layer 1: Docker Container Isolation (when enabled)

| Security Feature | Implementation |
|------------------|----------------|
| Network isolation | `--network=none` |
| Filesystem isolation | `--read-only` + tmpfs |
| Capability dropping | `--cap-drop=ALL` |
| Resource limits | `--memory`, `--cpus`, `--pids-limit` |
| User namespace | `--user=65534:65534` (nobody) |
| Privilege escalation | `--security-opt=no-new-privileges` |

#### Layer 2: Python Sandbox

| Security Feature | Implementation |
|------------------|----------------|
| Restricted builtins | Remove `eval`, `exec`, `open`, `__import__`, etc. |
| Module whitelist | Only allow safe modules: `math`, `json`, `datetime`, etc. |
| Resource limits | `resource.setrlimit()` for CPU, memory, files |
| Process limits | `RLIMIT_NPROC=1` to prevent fork bombs |

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

### Trade-offs

| Decision | Pros | Cons |
|----------|------|------|
| Docker + Python sandbox | Defense in depth, strong isolation | Slower startup (~100ms), requires Docker |
| Whitelist vs blocklist | More secure, explicit control | Less permissive, may need updates |
| In-memory task store | Simple, fast | Lost on restart, no persistence |
| SSE vs WebSocket | Simpler, HTTP-compatible | One-way only |

### Security Comparison

| Attack Vector | Subprocess Only | Docker + Sandbox |
|---------------|-----------------|------------------|
| Module import bypass | Partial protection | ✓ Blocked |
| `__class__` escape | Vulnerable | ✓ Blocked by whitelist |
| Fork bomb | Blocked by import | ✓ Blocked by `--pids-limit` |
| Network access | Blocked by import | ✓ Blocked by `--network=none` |
| File system access | Blocked by builtins | ✓ Blocked by `--read-only` |
| Memory exhaustion | `RLIMIT_AS` | ✓ `--memory` (more reliable) |

### What's NOT Implemented (production considerations)

1. **Persistent task storage** - Database for task history
2. **Rate limiting** - Prevent abuse
3. **Authentication** - Control who can execute code
4. **Seccomp profiles** - Fine-grained syscall filtering
5. **gVisor/Firecracker** - Even stronger isolation

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

## Running Tests

```bash
# Run basic test examples
python test_examples.py

# Run security test suite (tests sandbox escapes)
python security_tests.py
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
