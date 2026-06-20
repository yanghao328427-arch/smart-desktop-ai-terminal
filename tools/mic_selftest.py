from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import serial


def drain_serial(port: serial.Serial) -> None:
    while port.in_waiting:
        raw = port.readline()
        if raw:
            print(raw.decode("utf-8", errors="replace").rstrip())


def fetch_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def poll_selftest(
    base_url: str,
    device_id: str,
    phrase: str,
    timeout: float,
    port: serial.Serial | None = None,
    previous_audio_path: str | None = None,
) -> int:
    state_url = f"{base_url.rstrip('/')}/api/state/{device_id}"
    deadline = time.time() + timeout
    last_state: dict[str, Any] | None = None
    while time.time() < deadline:
        if port is not None:
            drain_serial(port)
        try:
            state = fetch_json(state_url)
        except (OSError, URLError, TimeoutError) as exc:
            print(f"[state] wait: {exc}")
            time.sleep(1)
            continue

        last_state = state
        sensors = state.get("sensors") or {}
        expected = sensors.get("mic_selftest_expected")
        audio_path = sensors.get("last_audio_path")
        fresh_audio = not previous_audio_path or audio_path != previous_audio_path
        if expected == phrase and fresh_audio:
            ok = bool(sensors.get("mic_selftest_ok"))
            text = sensors.get("mic_selftest_text") or ""
            provider = sensors.get("mic_selftest_provider") or ""
            error = sensors.get("mic_selftest_error") or ""
            print(f"[result] ok={ok} provider={provider}")
            print(f"[result] expected={expected}")
            print(f"[result] recognized={text}")
            if error:
                print(f"[result] error={error}")
            return 0 if ok else 2

        voice_state = state.get("voice_state")
        print(f"[state] voice_state={voice_state} waiting for selftest result...")
        time.sleep(1)

    if port is not None:
        drain_serial(port)
    if last_state is not None:
        sensors = last_state.get("sensors") or {}
        print("[result] timeout")
        print(json.dumps(
            {
                "voice_state": last_state.get("voice_state"),
                "last_asr_text": last_state.get("last_asr_text"),
                "mic_selftest_expected": sensors.get("mic_selftest_expected"),
                "mic_selftest_text": sensors.get("mic_selftest_text"),
                "mic_selftest_ok": sensors.get("mic_selftest_ok"),
                "mic_selftest_error": sensors.get("mic_selftest_error"),
            },
            ensure_ascii=False,
            indent=2,
        ))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger ESP32S3 microphone self-test and poll backend state.")
    parser.add_argument("--port", default="COM8")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--base-url", default="http://127.0.0.1:8083")
    parser.add_argument("--device-id", default="desktop-agent-001")
    parser.add_argument("--phrase", default="语音链路正常")
    parser.add_argument("--timeout", type=float, default=35)
    parser.add_argument("--no-serial", action="store_true", help="Only poll the backend state; do not write to serial.")
    args = parser.parse_args()
    state_url = f"{args.base_url.rstrip('/')}/api/state/{args.device_id}"
    try:
        previous_state = fetch_json(state_url)
        previous_audio_path = ((previous_state.get("sensors") or {}).get("last_audio_path") or "")
    except (OSError, URLError, TimeoutError):
        previous_audio_path = ""

    if args.no_serial:
        return poll_selftest(args.base_url, args.device_id, args.phrase, args.timeout)

    print(f"[serial] {args.port} > CFG:MIC:SELFTEST:{args.phrase}")
    with serial.Serial(args.port, args.baud, timeout=0.2) as port:
        time.sleep(1.2)
        drain_serial(port)
        port.write((f"CFG:MIC:SELFTEST:{args.phrase}\n").encode("utf-8"))
        port.flush()
        return poll_selftest(
            args.base_url,
            args.device_id,
            args.phrase,
            args.timeout,
            port,
            previous_audio_path=previous_audio_path,
        )


if __name__ == "__main__":
    raise SystemExit(main())
