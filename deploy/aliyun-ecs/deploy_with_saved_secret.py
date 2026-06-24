from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import paramiko


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRET_PATH = Path(__file__).with_name("server_secret.local.json")
ARCHIVE_PATH = PROJECT_ROOT / "dist" / "smartdesk-ecs-release.tar.gz"
INSTALLER_PATH = Path(__file__).with_name("install_release.sh")


def load_secret() -> dict[str, object]:
    payload = json.loads(SECRET_PATH.read_text(encoding="utf-8-sig"))
    password = str(payload.get("password") or "")
    if not password or "请只替换" in password:
        raise RuntimeError(f"Fill the password in {SECRET_PATH} first.")
    return payload


def connect(secret: dict[str, object]) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        str(secret["host"]),
        port=int(secret.get("port", 22)),
        username=str(secret["username"]),
        password=str(secret["password"]),
        look_for_keys=False,
        allow_agent=False,
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
    )
    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(30)
    return client


def run_streaming(client: paramiko.SSHClient, command: str) -> int:
    transport = client.get_transport()
    if transport is None:
        raise RuntimeError("SSH transport is not available.")
    channel = transport.open_session(timeout=20)
    channel.exec_command(command)
    channel.settimeout(1.0)
    while True:
        received = False
        if channel.recv_ready():
            sys.stdout.write(channel.recv(4096).decode("utf-8", errors="replace"))
            sys.stdout.flush()
            received = True
        if channel.recv_stderr_ready():
            sys.stderr.write(channel.recv_stderr(4096).decode("utf-8", errors="replace"))
            sys.stderr.flush()
            received = True
        if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
            return channel.recv_exit_status()
        if not received:
            time.sleep(0.2)


def main() -> int:
    if not ARCHIVE_PATH.exists():
        raise RuntimeError(f"Build the release archive first: {ARCHIVE_PATH}")
    secret = load_secret()
    client = connect(secret)
    try:
        sftp = client.open_sftp()
        try:
            sftp.put(str(ARCHIVE_PATH), "/tmp/smartdesk-ecs-release.tar.gz")
            sftp.put(str(INSTALLER_PATH), "/tmp/install_release.sh")
            sftp.chmod("/tmp/install_release.sh", 0o755)
        finally:
            sftp.close()
        return run_streaming(
            client,
            "bash /tmp/install_release.sh /tmp/smartdesk-ecs-release.tar.gz",
        )
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
