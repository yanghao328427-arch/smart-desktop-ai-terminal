from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
from typing import Any


DEFAULT_BASE_URL = "https://8-163-38-158.sslip.io"
DEFAULT_TURNS = [
    "你是谁，能像朋友一样陪我聊几句吗？",
    "现在状态怎么样？结合温湿度和距离告诉我。",
    "你记得我刚才问了什么吗？顺便给我一个学习建议。",
]


def resolve_control_token(explicit: str | None = None) -> str:
    if explicit:
        return explicit.strip()
    configured = os.environ.get("CONTROL_TOKEN", "").strip()
    if configured:
        return configured
    env_path = Path(__file__).resolve().parents[1] / "backend" / ".env"
    if not env_path.exists():
        return ""
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "CONTROL_TOKEN":
            return value.strip().strip("'\"")
    return ""


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 35,
    control_token: str = "",
) -> dict[str, Any]:
    data = None
    headers = {"Content-Type": "application/json"}
    if control_token:
        headers["X-Demo-Token"] = control_token
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def short_text(text: str, limit: int = 90) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def wait_for_acks(
    base_url: str,
    device_id: str,
    timeout_seconds: float,
    control_token: str = "",
) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    diagnostics = request_json(
        "GET",
        f"{base_url}/api/realtime/diagnostics/{device_id}",
        control_token=control_token,
    )
    while diagnostics["state"].get("pending_action_count", 0) and time.monotonic() < deadline:
        time.sleep(0.5)
        diagnostics = request_json(
            "GET",
            f"{base_url}/api/realtime/diagnostics/{device_id}",
            control_token=control_token,
        )
    return diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a safe cloud-dialogue smoke test against the running backend."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--device-id", default="desktop-agent-001")
    parser.add_argument(
        "--control-token",
        default=None,
        help="Control token override. By default reads CONTROL_TOKEN or backend/.env without printing it.",
    )
    parser.add_argument(
        "--turn",
        action="append",
        dest="turns",
        help="Dialogue turn to send. Can be repeated. Defaults to a three-turn defense demo.",
    )
    parser.add_argument(
        "--require-cloud",
        action="store_true",
        help="Return a non-zero exit code if the backend is not using a cloud model.",
    )
    parser.add_argument(
        "--ack-wait-seconds",
        type=float,
        default=10.0,
        help="Seconds to wait for STM32 ACKs before printing the final summary.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    turns = args.turns or DEFAULT_TURNS
    control_token = resolve_control_token(args.control_token)

    try:
        health = request_json("GET", f"{base_url}/api/health", control_token=control_token)
        state_before = request_json(
            "GET",
            f"{base_url}/api/state/{args.device_id}",
            control_token=control_token,
        )

        transcript: list[dict[str, Any]] = []
        for index, text in enumerate(turns, start=1):
            chat = request_json(
                "POST",
                f"{base_url}/api/chat",
                {"device_id": args.device_id, "text": text, "source": "cloud_smoke"},
                control_token=control_token,
            )
            fallback_detected = "云端暂不可用" in chat["reply"] or "已使用本地规则" in chat["reply"]
            transcript.append(
                {
                    "turn": index,
                    "user": text,
                    "reply": short_text(chat["reply"]),
                    "speech": short_text(chat.get("speech", "")),
                    "cloud_fallback_detected": fallback_detected,
                    "commands": len(chat["commands"]),
                    "actions": [action["type"] for action in chat["actions"]],
                }
            )
            wait_for_acks(
                base_url,
                args.device_id,
                args.ack_wait_seconds,
                control_token=control_token,
            )

        diagnostics = wait_for_acks(
            base_url,
            args.device_id,
            args.ack_wait_seconds,
            control_token=control_token,
        )
    except urllib.error.HTTPError as exc:
        error = (
            f"HTTP {exc.code}: control token is missing or invalid"
            if exc.code in {401, 403}
            else f"HTTP {exc.code}: {exc.reason}"
        )
        print(json.dumps({"ok": False, "error": error}, ensure_ascii=False, indent=2))
        return 1
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    cloud_fallback_detected = any(turn["cloud_fallback_detected"] for turn in transcript)
    cloud_verified = bool(health.get("cloud_ready", False)) and not cloud_fallback_detected
    summary = {
        "ok": True,
        "cloud_ready": health.get("cloud_ready", False),
        "cloud_fallback_detected": cloud_fallback_detected,
        "ai_provider": health.get("ai_provider"),
        "ai_model": health.get("ai_model"),
        "device_online": state_before.get("online"),
        "uart_ok": state_before.get("uart_ok"),
        "session_connected": state_before.get("session_connected"),
        "sensor_keys": sorted((state_before.get("sensors") or {}).keys()),
        "turns": transcript,
        "ack_ok_count": diagnostics["state"].get("ack_ok_count"),
        "ack_err_count": diagnostics["state"].get("ack_err_count"),
        "pending_action_count": diagnostics["state"].get("pending_action_count"),
        "ack_wait_seconds": args.ack_wait_seconds,
        "note": "Cloud Qwen path verified; no API keys are printed."
        if cloud_verified
        else "cloud_ready=false or fallback detected means the backend is not fully using the cloud model.",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    return 2 if args.require_cloud and (not summary["cloud_ready"] or cloud_fallback_detected) else 0


if __name__ == "__main__":
    sys.exit(main())
