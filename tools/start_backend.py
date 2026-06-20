from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def get_health(url: str) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def write_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def write_log_tail(path: Path, label: str, line_count: int = 40) -> None:
    if not path.exists():
        return

    print()
    print(f"{label} ({path}):")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-line_count:]:
        print(line)


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the FastAPI backend and print /api/health.")
    parser.add_argument("--bind-host", default="0.0.0.0")
    parser.add_argument("--health-host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    backend_dir = repo_root / "backend"
    tmp_dir = repo_root / ".tmp"

    if not backend_dir.exists():
        print(f"ERROR: backend directory not found: {backend_dir}")
        return 1

    tmp_dir.mkdir(parents=True, exist_ok=True)

    health_url = f"http://{args.health_host}:{args.port}/api/health"
    health = get_health(health_url)
    if health and health.get("status") == "ok":
        print(f"Backend already healthy at {health_url}")
        write_json(health)
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    stdout_log = tmp_dir / f"backend-{args.port}-{stamp}.out.log"
    stderr_log = tmp_dir / f"backend-{args.port}-{stamp}.err.log"

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        args.bind_host,
        "--port",
        str(args.port),
    ]
    if args.reload:
        command.append("--reload")

    creationflags = 0
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)

    with stdout_log.open("wb") as stdout, stderr_log.open("wb") as stderr:
        process = subprocess.Popen(
            command,
            cwd=backend_dir,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )

    print(f"Started backend process PID {process.pid}. Waiting for {health_url} ...")

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        time.sleep(0.5)

        health = get_health(health_url)
        if health and health.get("status") == "ok":
            print(f"Health check OK at {health_url}")
            write_json(health)
            print()
            print("Logs:")
            print(f"  stdout: {stdout_log}")
            print(f"  stderr: {stderr_log}")
            return 0

        exit_code = process.poll()
        if exit_code is not None:
            print(f"ERROR: backend process exited before health check passed. Exit code: {exit_code}")
            write_log_tail(stdout_log, "stdout")
            write_log_tail(stderr_log, "stderr")
            return exit_code or 1

    print(f"ERROR: timed out after {args.timeout} seconds waiting for {health_url}")
    write_log_tail(stdout_log, "stdout")
    write_log_tail(stderr_log, "stderr")
    stop_process(process)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
