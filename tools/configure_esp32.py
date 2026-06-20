from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import serial


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_line(port: serial.Serial, line: str, *, echo: bool = True) -> None:
    if echo:
        print(f"> {line}")
    else:
        print("> <hidden>")
    port.write((line + "\n").encode("utf-8"))
    port.flush()
    time.sleep(0.5)
    while port.in_waiting:
        print(port.readline().decode("utf-8", errors="replace").rstrip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure ESP32S3 Wi-Fi/server from local backend/.env.")
    parser.add_argument("--port", default="COM8")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--server", help="Example: http://192.168.0.10:8083")
    parser.add_argument("--env", default=str(Path(__file__).resolve().parents[1] / "backend" / ".env"))
    args = parser.parse_args()

    env = {**load_env(Path(args.env)), **os.environ}
    ssid = env.get("WIFI_SSID", "")
    password = env.get("WIFI_PASSWORD", "")
    server = args.server or env.get("BACKEND_SERVER_URL", "")

    if not ssid or not password:
        print("ERROR: WIFI_SSID and WIFI_PASSWORD must exist in local backend/.env or environment.")
        return 1
    if not server:
        print("ERROR: provide --server or set BACKEND_SERVER_URL in local backend/.env.")
        return 1

    with serial.Serial(args.port, args.baud, timeout=1) as port:
        time.sleep(1.5)
        write_line(port, f"CFG:WIFI:{ssid},{password}", echo=False)
        write_line(port, f"CFG:SERVER:{server}")
        write_line(port, "CFG:WIFI:SHOW")
        write_line(port, "CFG:UART:PING")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
