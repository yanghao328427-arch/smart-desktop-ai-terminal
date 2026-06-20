from __future__ import annotations

import argparse
import sys
import threading
import time

import serial


def reader(port: serial.Serial, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            data = port.readline()
        except serial.SerialException as exc:
            print(f"\n[serial] read error: {exc}")
            stop.set()
            return
        if data:
            print(data.decode("utf-8", errors="replace").rstrip(), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send lines to COM7/COM8 and optionally monitor replies.")
    parser.add_argument("port", help="Example: COM7 or COM8")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--line", action="append", default=[], help="Line to send. Can be repeated.")
    parser.add_argument("--monitor", action="store_true", help="Keep reading after sending lines.")
    parser.add_argument("--monitor-seconds", type=float, default=0.0, help="Stop monitoring after this many seconds.")
    parser.add_argument("--open-delay", type=float, default=0.0, help="Seconds to wait after opening the port.")
    parser.add_argument("--delay", type=float, default=0.2)
    args = parser.parse_args()

    stop = threading.Event()
    try:
        with serial.Serial(args.port, args.baud, timeout=0.2) as port:
            thread = threading.Thread(target=reader, args=(port, stop), daemon=True)
            thread.start()

            if args.open_delay > 0:
                time.sleep(args.open_delay)

            for line in args.line:
                port.write((line + "\n").encode("utf-8"))
                port.flush()
                time.sleep(args.delay)

            if args.monitor or not args.line:
                print("[serial] monitor mode; press Ctrl+C to exit", flush=True)
                monitor_until = time.monotonic() + args.monitor_seconds if args.monitor_seconds > 0 else None
                while monitor_until is None or time.monotonic() < monitor_until:
                    time.sleep(0.2)
            time.sleep(args.delay)
            stop.set()
            thread.join(timeout=1)
            return 0
    except KeyboardInterrupt:
        stop.set()
        return 0
    except serial.SerialException as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
