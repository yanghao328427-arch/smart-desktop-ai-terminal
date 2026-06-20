from __future__ import annotations

import argparse
import json
import math
import sys
import time
import uuid
import wave
from array import array
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8083"
DEFAULT_DEVICE_ID = "desktop-agent-001"
KEY2_LINE = "BT:BTN:KEY2:SHORT"


def configure_text_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def request_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 20.0) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def encode_multipart(
    *,
    fields: dict[str, str],
    file_field: str,
    filename: str,
    content_type: str,
    content: bytes,
) -> tuple[bytes, str]:
    boundary = f"----laptop-mic-sidecar-{uuid.uuid4().hex}"
    parts: list[bytes] = []

    for name, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    parts.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("ascii"),
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def post_wav(
    *,
    base_url: str,
    device_id: str,
    wav_path: Path,
    inject: bool,
    source: str,
    sample_rate: int,
    channels: int,
) -> dict[str, Any]:
    content = wav_path.read_bytes()
    body, content_type = encode_multipart(
        fields={
            "device_id": device_id,
            "inject": "true" if inject else "false",
            "source": source,
            "audio_format": "wav",
            "sample_rate": str(sample_rate),
            "channels": str(channels),
        },
        file_field="audio",
        filename=wav_path.name,
        content_type="audio/wav",
        content=content,
    )
    request = Request(
        f"{base_url.rstrip('/')}/api/asr/transcribe",
        data=body,
        headers={"Content-Type": content_type, "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def list_audio_devices() -> int:
    configure_text_output()
    try:
        import sounddevice as sd
    except ImportError:
        print("ERROR: install sounddevice first: python -m pip install sounddevice")
        return 1

    print(sd.query_devices())
    return 0


def cue_beep(enabled: bool) -> None:
    if not enabled:
        return
    try:
        import winsound

        winsound.Beep(1200, 450)
    except Exception:
        print("\a", end="", flush=True)


def wait_before_record(seconds: float, *, beep: bool) -> None:
    print("[privacy] Laptop microphone recording is about to begin. Please get ready.", flush=True)
    if seconds > 0:
        print(f"[cue] recording starts after {seconds:.1f}s")
        time.sleep(seconds)
    cue_beep(beep)
    if beep:
        time.sleep(0.7)


def record_wav(
    *,
    output_path: Path,
    seconds: float,
    sample_rate: int,
    channels: int,
    input_device: str | int | None,
) -> dict[str, Any]:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is required: python -m pip install sounddevice") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio = bytearray()

    def callback(indata: bytes, frames: int, time_info: object, status: object) -> None:
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        audio.extend(indata)

    print(f"[record] {seconds:.1f}s, {sample_rate} Hz, {channels} channel(s)")
    try:
        with sd.RawInputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
            device=input_device,
            callback=callback,
        ):
            time.sleep(seconds)
    except Exception as exc:
        raise RuntimeError(f"audio input error: {exc}") from exc

    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(audio))

    return audio_stats(bytes(audio), sample_rate=sample_rate, channels=channels, path=output_path)


def audio_stats(raw_pcm: bytes, *, sample_rate: int, channels: int, path: Path) -> dict[str, Any]:
    samples = array("h")
    samples.frombytes(raw_pcm)
    if sys.byteorder != "little":
        samples.byteswap()

    if not samples:
        return {
            "path": str(path),
            "bytes": len(raw_pcm),
            "duration_seconds": 0,
            "peak": 0,
            "rms": 0,
        }

    peak = max(abs(value) for value in samples)
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    frames = len(samples) / max(1, channels)
    return {
        "path": str(path),
        "bytes": len(raw_pcm),
        "duration_seconds": round(frames / sample_rate, 3),
        "peak": peak,
        "rms": round(rms, 1),
    }


def wait_for_key2(*, port_name: str, baud: int, key2_line: str, timeout_seconds: float, open_delay: float) -> bool:
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("pyserial is required for --trigger key2: python -m pip install pyserial") from exc

    import serial.serialutil

    deadline = time.monotonic() + timeout_seconds
    print(f"[serial] listening on {port_name} for {key2_line}")
    try:
        with serial.Serial(port_name, baud, timeout=0.2) as port:
            if open_delay > 0:
                time.sleep(open_delay)
            while time.monotonic() < deadline:
                raw = port.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    print(f"[serial] {line}")
                if line == key2_line:
                    print("[trigger] KEY2 detected")
                    return True
    except serial.serialutil.SerialException as exc:
        raise RuntimeError(f"serial error: {exc}") from exc

    return False


def diagnostics(base_url: str, device_id: str) -> dict[str, Any]:
    return request_json("GET", f"{base_url.rstrip('/')}/api/realtime/diagnostics/{device_id}", timeout=10)


def wait_for_action_statuses(
    *,
    base_url: str,
    device_id: str,
    action_ids: list[str],
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    expected = set(action_ids)
    latest = diagnostics(base_url, device_id)

    while time.monotonic() < deadline:
        recent = latest.get("recent_actions") or []
        statuses = {item.get("id"): item.get("status") for item in recent if item.get("id") in expected}
        if expected and expected.issubset(statuses) and all(status in {"acked", "failed"} for status in statuses.values()):
            return latest
        if not expected and latest.get("state", {}).get("pending_action_count", 0) == 0:
            return latest
        time.sleep(0.5)
        latest = diagnostics(base_url, device_id)

    return latest


def output_path_from_args(value: str, source: str) -> Path:
    if value:
        return Path(value)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Path(".tmp") / "laptop_mic_sidecar" / f"{stamp}-{source}.wav"


def parse_device(value: str) -> str | int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def main() -> int:
    configure_text_output()
    parser = argparse.ArgumentParser(
        description="Record laptop microphone audio as a sidecar and upload it to the existing backend ASR endpoint."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument("--trigger", choices=["manual", "key2"], default="manual")
    parser.add_argument("--port", default="", help="Serial port for --trigger key2, for example COM7 or COM8.")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--key2-line", default=KEY2_LINE)
    parser.add_argument("--key2-timeout", type=float, default=60.0)
    parser.add_argument("--serial-open-delay", type=float, default=0.5)
    parser.add_argument("--record-seconds", type=float, default=6.0)
    parser.add_argument("--pre-delay", type=float, default=0.0, help="Seconds to wait before recording.")
    parser.add_argument("--cue-beep", action="store_true", help="Play a short beep immediately before recording.")
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--input-device", default="", help="sounddevice input device index or name.")
    parser.add_argument("--output", default="", help="WAV output path. Defaults to .tmp/laptop_mic_sidecar/*.wav")
    parser.add_argument("--source", default="laptop_mic_sidecar")
    parser.add_argument("--inject", action="store_true", help="Continue from ASR text into AI/action/STM32 command chain.")
    parser.add_argument("--wait-ack-seconds", type=float, default=20.0)
    parser.add_argument("--list-devices", action="store_true")
    args = parser.parse_args()

    if args.list_devices:
        return list_audio_devices()

    if args.channels != 1:
        print("ERROR: backend ASR path currently expects mono audio; use --channels 1.", file=sys.stderr)
        return 2
    if args.trigger == "key2" and not args.port:
        print("ERROR: --port is required with --trigger key2.", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    output_path = output_path_from_args(args.output, args.source)

    try:
        health = request_json("GET", f"{base_url}/api/health", timeout=10)
        before = diagnostics(base_url, args.device_id)

        if args.trigger == "key2":
            if not wait_for_key2(
                port_name=args.port,
                baud=args.baud,
                key2_line=args.key2_line,
                timeout_seconds=args.key2_timeout,
                open_delay=args.serial_open_delay,
            ):
                print(json.dumps({"ok": False, "error": "KEY2 trigger timeout"}, ensure_ascii=False, indent=2))
                return 1
        else:
            print("[trigger] manual recording starts now")

        wait_before_record(args.pre_delay, beep=args.cue_beep)
        audio = record_wav(
            output_path=output_path,
            seconds=args.record_seconds,
            sample_rate=args.sample_rate,
            channels=args.channels,
            input_device=parse_device(args.input_device),
        )
        response = post_wav(
            base_url=base_url,
            device_id=args.device_id,
            wav_path=output_path,
            inject=args.inject,
            source=args.source,
            sample_rate=args.sample_rate,
            channels=args.channels,
        )

        action_ids = [
            action.get("id")
            for action in (((response.get("chat") or {}).get("actions")) or [])
            if action.get("id")
        ]
        after = wait_for_action_statuses(
            base_url=base_url,
            device_id=args.device_id,
            action_ids=action_ids,
            timeout_seconds=args.wait_ack_seconds if args.inject else 0.0,
        )
    except (OSError, URLError, HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    recent_statuses = {
        item.get("id"): item.get("status")
        for item in (after.get("recent_actions") or [])
        if item.get("id") in set(action_ids)
    }
    summary = {
        "ok": bool(response.get("ok")),
        "trigger": args.trigger,
        "inject": args.inject,
        "health": {
            "ai_provider": health.get("ai_provider"),
            "ai_model": health.get("ai_model"),
            "cloud_ready": health.get("cloud_ready"),
        },
        "audio": audio,
        "asr": {
            "ok": response.get("ok"),
            "provider": response.get("provider"),
            "text": response.get("text"),
            "audio_bytes": response.get("audio_bytes"),
            "backend_audio_path": response.get("audio_path"),
            "error": response.get("error"),
        },
        "actions": {
            "created": action_ids,
            "statuses": recent_statuses,
            "ack_ok_count_before": before.get("state", {}).get("ack_ok_count"),
            "ack_ok_count_after": after.get("state", {}).get("ack_ok_count"),
            "ack_err_count_after": after.get("state", {}).get("ack_err_count"),
            "pending_action_count_after": after.get("state", {}).get("pending_action_count"),
            "last_ack": after.get("state", {}).get("last_ack"),
        },
        "note": "This sidecar proves laptop microphone input only; it does not prove the ESP32S3 onboard mic path.",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if response.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
