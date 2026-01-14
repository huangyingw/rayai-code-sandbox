# Code Executor Sandbox

A secure HTTP API for executing arbitrary Python code with real-time streaming output.

## Setup

### Requirements

- Python 3.10+
- Unix-like OS (Linux/macOS) for resource limits

### Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Server

```bash
# Development
python main.py

# Or with uvicorn directly
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.

API documentation: `http://localhost:8000/docs`

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

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     FastAPI Server                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │POST /execute│  │GET /tasks/id│  │GET /tasks/stream│ │
│  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘ │
│         │                │                   │          │
│         ▼                ▼                   ▼          │
│  ┌──────────────────────────────────────────────────┐  │
│  │                  CodeExecutor                     │  │
│  │  - Task management (in-memory store)             │  │
│  │  - Output buffering for streaming                │  │
│  └──────────────────────┬───────────────────────────┘  │
│                         │                               │
│                         ▼                               │
│  ┌──────────────────────────────────────────────────┐  │
│  │              Sandbox Subprocess                   │  │
│  │  - Resource limits (CPU, memory, files)          │  │
│  │  - Restricted builtins                           │  │
│  │  - Blocked dangerous modules                     │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Security Measures

1. **Process Isolation**: Code runs in a separate subprocess, not in the main server process.

2. **Resource Limits** (via `resource` module):
   - CPU time: 10 seconds max
   - Memory: 128MB max
   - File size: 1MB max
   - Open files: 10 max

3. **Restricted Builtins**: Dangerous functions are removed:
   - `eval`, `exec`, `compile` - prevent dynamic code execution
   - `open`, `input` - prevent file/stdin access
   - `__import__` - replaced with restricted version
   - `globals`, `locals`, `vars`, `dir` - prevent introspection

4. **Module Blocklist**: Dangerous modules are blocked:
   - `os`, `subprocess`, `shutil` - system commands
   - `socket`, `http`, `urllib`, `requests` - network access
   - `ctypes` - low-level memory access
   - `multiprocessing`, `threading` - resource exhaustion
   - `pickle`, `marshal` - deserialization attacks
   - And more...

5. **Output Limits**: Maximum 1MB output to prevent memory exhaustion.

6. **Timeout Protection**: Hard timeout with process kill.

### Trade-offs

| Decision | Pros | Cons |
|----------|------|------|
| Subprocess vs Docker | Simple, fast startup, no dependencies | Less isolation than containers |
| Blocklist vs allowlist | More permissive, allows stdlib | May miss new attack vectors |
| In-memory task store | Simple, fast | Lost on restart, no persistence |
| SSE vs WebSocket | Simpler, HTTP-compatible | One-way only |

### What's NOT Implemented (would need more time)

1. **Docker/container isolation** - Would provide better security through namespaces, cgroups
2. **Persistent task storage** - Database for task history
3. **Rate limiting** - Prevent abuse
4. **Authentication** - Control who can execute code
5. **Network isolation** - Block network at OS level
6. **Seccomp/AppArmor** - Syscall filtering

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
# Run the test examples
python test_examples.py
```
