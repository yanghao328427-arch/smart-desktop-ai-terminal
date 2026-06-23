from __future__ import annotations

import argparse
import getpass
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
    parser.add_argument(
        "--server-only",
        action="store_true",
        help="Update only CFG:SERVER; do not read or resend Wi-Fi credentials.",
    )
    parser.add_argument(
        "--prompt-wifi",
        action="store_true",
        help="Prompt for Wi-Fi SSID/password without saving them on the computer.",
    )
    parser.add_argument(
        "--open-delay",
        type=float,
        default=8.0,
        help="Seconds to wait after opening the ESP32 USB serial port (default: 8).",
    )
    parser.add_argument("--device-token", help="Optional DEVICE_TOKEN for ESP32 RFID/context posts.")
    parser.add_argument("--env", default=str(Path(__file__).resolve().parents[1] / "backend" / ".env"))
    args = parser.parse_args()

    env = {**load_env(Path(args.env)), **os.environ}
    ssid = env.get("WIFI_SSID", "")
    password = env.get("WIFI_PASSWORD", "")
    server = args.server or env.get("BACKEND_SERVER_URL", "")
    device_token = args.device_token or env.get("DEVICE_TOKEN", "") or env.get("ESP32_DEVICE_TOKEN", "")

    if args.server_only and args.prompt_wifi:
        parser.error("--server-only and --prompt-wifi cannot be used together")
    if args.prompt_wifi:
        ssid = input("Hotspot SSID: ").strip()
        password = getpass.getpass("Hotspot password: ")

    if not args.server_only and (not ssid or not password):
        print("ERROR: WIFI_SSID and WIFI_PASSWORD must exist in local backend/.env or environment.")
        return 1
    if not server:
        print("ERROR: provide --server or set BACKEND_SERVER_URL in local backend/.env.")
        return 1
    if args.open_delay < 0:
        parser.error("--open-delay must be non-negative")

    with serial.Serial(args.port, args.baud, timeout=1) as port:
        time.sleep(args.open_delay)
        if not args.server_only:
            write_line(port, f"CFG:WIFI:{ssid},{password}", echo=False)
        write_line(port, f"CFG:SERVER:{server}")
        if device_token and not args.server_only:
            write_line(port, f"CFG:TOKEN:{device_token}", echo=False)
        write_line(port, "CFG:WIFI:SHOW")
        write_line(port, "CFG:UART:PING")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
