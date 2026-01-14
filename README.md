# Code Executor Sandbox

A secure HTTP API for executing arbitrary Python code in Docker containers with real-time streaming.

## Quick Start

```bash
make setup build run
```

Test it:
```bash
curl -X POST http://localhost:8000/execute \
  -H "Content-Type: application/json" \
  -d '{"code": "print(sum(range(10)))"}'
# {"task_id": "abc123"}

curl http://localhost:8000/tasks/abc123
# {"status": "completed", "stdout": "45\n", ...}
```

**Requirements**: Python 3.10+, Docker

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/execute` | Submit code, returns `{"task_id": "..."}` |
| GET | `/tasks/{id}` | Get task result and status |
| GET | `/tasks/{id}/stream` | Stream output via SSE |
| DELETE | `/tasks/{id}` | Kill running task |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Server                                             │
│  POST /execute  │  GET /tasks/{id}  │  GET /tasks/stream    │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  SandboxExecutor                                            │
│  ┌─────────────────┐  ┌─────────────────┐                   │
│  │ TaskStorage     │  │ DockerRunner    │                   │
│  │ (pluggable)     │  │ (per-task       │                   │
│  └─────────────────┘  │  container)     │                   │
│                       └─────────────────┘                   │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Docker Container (isolated per task)                       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Layer 1: Container Security                            │ │
│  │ • --network=none    • --read-only    • --cap-drop=ALL  │ │
│  │ • --memory=128m     • --pids-limit=50  • seccomp       │ │
│  ├────────────────────────────────────────────────────────┤ │
│  │ Layer 2: Python Sandbox                                │ │
│  │ • Restricted builtins  • Module whitelist              │ │
│  │ • Attribute blocking   • Resource limits               │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Security

**Defense in Depth**: Two security layers ensure protection even if one is bypassed.

| Attack | Protection |
|--------|------------|
| Network access | `--network=none` (container level) |
| File system | `--read-only` + restricted builtins |
| Fork bomb | `--pids-limit=50` + seccomp filter |
| Memory bomb | `--memory=128m` (Docker enforced) |
| Module import | Whitelist: `math`, `json`, `datetime`, `collections`, etc. |
| `__class__` escape | Pattern scanning + attribute blocking |
| eval/exec | Removed from builtins |

## Test Examples

**1. Malicious Code (Blocked)**
```python
import os; os.system('rm -rf /')
# ImportError: Module 'os' is not allowed
```

**2. Resource Exhaustion (Killed)**
```python
while True: pass
# Task timeout after 10 seconds
```

**3. Valid Code (Success)**
```python
import math
print(f"Pi = {math.pi:.4f}")
# Output: Pi = 3.1416
```

Run full test suite:
```bash
make test-unit      # Unit tests
make test-security  # Security tests (start server first)
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `EXECUTOR_TIMEOUT` | 10 | Execution timeout (seconds) |
| `EXECUTOR_MAX_MEMORY` | 128 | Memory limit (MB) |
| `EXECUTOR_MAX_CONCURRENT` | 10 | Max concurrent tasks |
| `DOCKER_MEMORY_LIMIT` | 128m | Container memory |
| `DOCKER_PIDS_LIMIT` | 50 | Container process limit |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | 60 | Rate limit per IP |

## Project Structure

```
sandbox/
├── api/routes.py       # FastAPI endpoints
├── executor/
│   ├── sandbox.py      # Main executor
│   ├── docker.py       # Docker container management
│   └── wrapper.py      # Python sandbox template
├── storage/            # Task storage (pluggable)
├── config.py           # Environment-based config
└── models.py           # Data models

Dockerfile.sandbox      # Hardened container image
seccomp-profile.json    # Syscall filter rules
```

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Docker mandatory | Maximum isolation, defense in depth |
| One container per task | Complete isolation between tasks |
| Module whitelist | Explicit allow-list is more secure than blocklist |
| In-memory storage | Simple; can swap to Redis/DB via interface |
| SSE streaming | HTTP-compatible, simpler than WebSocket |

## Not Implemented (Production Considerations)

- **Authentication** - Who can execute code
- **Persistent storage** - Task history in database
- **Distributed execution** - Multi-node scaling
- **gVisor/Firecracker** - Stronger isolation options
