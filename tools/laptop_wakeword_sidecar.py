from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

from laptop_mic_sidecar import (
    DEFAULT_BASE_URL,
    DEFAULT_DEVICE_ID,
    configure_text_output,
    diagnostics,
    list_audio_devices,
    parse_device,
    post_wav,
    record_wav,
    request_json,
    wait_before_record,
    wait_for_action_statuses,
)


DEFAULT_WAKE_PHRASES = ["灵宝灵宝", "你好灵宝"]
DEFAULT_WAKE_SOURCE = "laptop_wakeword_listener"
DEFAULT_COMMAND_SOURCE = "laptop_wakeword_command"


def normalize_for_wake_match(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def match_wake_phrases(text: str, phrases: list[str]) -> list[str]:
    normalized_text = normalize_for_wake_match(text)
    matched: list[str] = []
    for phrase in phrases:
        normalized_phrase = normalize_for_wake_match(phrase)
        if normalized_phrase and normalized_phrase in normalized_text:
            matched.append(phrase)
    return matched


def output_path(kind: str, source: str, sequence: int) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_source = re.sub(r"[^A-Za-z0-9_.-]+", "_", source).strip("_") or "laptop_wakeword"
    return Path(".tmp") / "laptop_wakeword_sidecar" / f"{stamp}-{sequence:03d}-{kind}-{safe_source}.wav"


def action_ids_from_response(response: dict[str, Any]) -> list[str]:
    return [
        action.get("id")
        for action in (((response.get("chat") or {}).get("actions")) or [])
        if action.get("id")
    ]


def recent_action_statuses(after: dict[str, Any], action_ids: list[str]) -> dict[str, str | None]:
    expected = set(action_ids)
    return {
        item.get("id"): item.get("status")
        for item in (after.get("recent_actions") or [])
        if item.get("id") in expected
    }


def run_wake_check(args: argparse.Namespace, sequence: int) -> dict[str, Any]:
    wav_path = output_path("wake", args.wake_source, sequence)
    print(
        "[privacy] Wake-word listening window is recording from the laptop microphone now "
        f"({args.wake_window_seconds:.1f}s).",
        flush=True,
    )
    audio = record_wav(
        output_path=wav_path,
        seconds=args.wake_window_seconds,
        sample_rate=args.sample_rate,
        channels=args.channels,
        input_device=parse_device(args.input_device),
    )
    response = post_wav(
        base_url=args.base_url,
        device_id=args.device_id,
        wav_path=wav_path,
        inject=False,
        source=args.wake_source,
        sample_rate=args.sample_rate,
        channels=args.channels,
    )
    text = str(response.get("text") or "")
    matches = match_wake_phrases(text, args.wake_phrase)
    result = {
        "state": "IDLE",
        "wake_check": sequence,
        "matched": bool(matches),
        "matches": matches,
        "asr": {
            "ok": response.get("ok"),
            "provider": response.get("provider"),
            "text": text,
            "error": response.get("error"),
        },
        "audio": audio,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def run_command_recording(args: argparse.Namespace, sequence: int, health: dict[str, Any]) -> dict[str, Any]:
    before = diagnostics(args.base_url, args.device_id)
    wav_path = output_path("command", args.command_source, sequence)

    print("[state] WAKE_DETECTED")
    print("[privacy] Wake word detected. Command recording is about to begin; please speak after the cue.", flush=True)
    wait_before_record(args.pre_delay, beep=not args.no_cue_beep)

    audio = record_wav(
        output_path=wav_path,
        seconds=args.record_seconds,
        sample_rate=args.sample_rate,
        channels=args.channels,
        input_device=parse_device(args.input_device),
    )
    response = post_wav(
        base_url=args.base_url,
        device_id=args.device_id,
        wav_path=wav_path,
        inject=args.inject,
        source=args.command_source,
        sample_rate=args.sample_rate,
        channels=args.channels,
    )
    action_ids = action_ids_from_response(response)
    after = wait_for_action_statuses(
        base_url=args.base_url,
        device_id=args.device_id,
        action_ids=action_ids,
        timeout_seconds=args.wait_ack_seconds if args.inject else 0.0,
    )
    summary = {
        "state": "EXECUTE" if args.inject else "ASR",
        "wake_check": sequence,
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
            "statuses": recent_action_statuses(after, action_ids),
            "ack_ok_count_before": before.get("state", {}).get("ack_ok_count"),
            "ack_ok_count_after": after.get("state", {}).get("ack_ok_count"),
            "ack_err_count_after": after.get("state", {}).get("ack_err_count"),
            "pending_action_count_after": after.get("state", {}).get("pending_action_count"),
            "last_ack": after.get("state", {}).get("last_ack"),
        },
        "note": (
            "This sidecar proves the laptop microphone temporary wake-word front-end only; "
            "it does not prove the ESP32S3 onboard microphone path."
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Temporary laptop microphone wake-word front-end. Wake detection uses short laptop-mic "
            "recordings uploaded to /api/asr/transcribe with inject=false; after a wake phrase, "
            "the command recording is uploaded with inject=true by default."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument(
        "--wake-phrase",
        action="append",
        default=[],
        help=f"Wake phrase to match after ASR. Repeatable. Default: {', '.join(DEFAULT_WAKE_PHRASES)}",
    )
    parser.add_argument("--wake-window-seconds", type=float, default=2.5)
    parser.add_argument("--wake-interval-seconds", type=float, default=0.2)
    parser.add_argument("--record-seconds", type=float, default=6.0)
    parser.add_argument("--pre-delay", type=float, default=1.5)
    parser.add_argument("--cooldown-seconds", type=float, default=2.0)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--input-device", default="", help="sounddevice input device index or name.")
    parser.add_argument("--wake-source", default=DEFAULT_WAKE_SOURCE)
    parser.add_argument("--command-source", default=DEFAULT_COMMAND_SOURCE)
    parser.add_argument("--no-cue-beep", action="store_true", help="Disable cue beeps before command recording.")
    parser.add_argument("--no-inject", dest="inject", action="store_false", help="ASR only; do not enter Qwen/action/ACK.")
    parser.set_defaults(inject=True)
    parser.add_argument("--wait-ack-seconds", type=float, default=20.0)
    parser.add_argument("--once", action="store_true", help="Exit after the first successful wake-command cycle.")
    parser.add_argument("--max-wake-checks", type=int, default=0, help="Stop after N wake checks. 0 means keep listening.")
    parser.add_argument("--confirm-start", action="store_true", help="Require Enter before wake listening starts.")
    parser.add_argument("--list-devices", action="store_true")
    return parser.parse_args()


def main() -> int:
    configure_text_output()
    args = parse_args()
    args.base_url = args.base_url.rstrip("/")
    if not args.wake_phrase:
        args.wake_phrase = DEFAULT_WAKE_PHRASES

    if args.list_devices:
        return list_audio_devices()
    if args.channels != 1:
        print("ERROR: backend ASR path currently expects mono audio; use --channels 1.", file=sys.stderr)
        return 2
    if args.wake_window_seconds <= 0 or args.record_seconds <= 0:
        print("ERROR: recording durations must be positive.", file=sys.stderr)
        return 2

    try:
        health = request_json("GET", f"{args.base_url}/api/health", timeout=10)
        print(
            "[privacy] Laptop wake-word listener is about to start. It records short laptop-mic "
            "wake windows and uploads them to /api/asr/transcribe with inject=false.",
            flush=True,
        )
        print(f"[wake] phrases={args.wake_phrase}")
        print("[note] This is a laptop-mic temporary front-end, not ESP32S3 onboard microphone proof.")
        if args.confirm_start:
            input("Press Enter to start wake-word listening...")

        wake_checks = 0
        completed_cycles = 0
        while args.max_wake_checks <= 0 or wake_checks < args.max_wake_checks:
            wake_checks += 1
            wake_result = run_wake_check(args, wake_checks)
            if not wake_result["matched"]:
                time.sleep(max(0.0, args.wake_interval_seconds))
                continue

            completed_cycles += 1
            run_command_recording(args, wake_checks, health)
            if args.once:
                break
            print(f"[state] COOLDOWN {args.cooldown_seconds:.1f}s")
            time.sleep(max(0.0, args.cooldown_seconds))

        print(json.dumps({"ok": True, "wake_checks": wake_checks, "completed_cycles": completed_cycles}, indent=2))
        return 0
    except KeyboardInterrupt:
        print("\n[stop] wake-word listener stopped by user.")
        return 130
    except (OSError, URLError, HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
