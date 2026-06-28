from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_BASE_URL = "https://8-163-38-158.sslip.io"
DEFAULT_DEVICE_ID = "desktop-agent-001"
SENSOR_KEYS = (
    "temperature_c",
    "humidity_pct",
    "distance_cm",
    "pot_raw",
    "ntc_raw",
    "tracking_signal",
    "encoder_position",
)


def request_json(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def age_seconds(value: object, now: datetime) -> float | None:
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return None
    return max(0.0, (now - timestamp).total_seconds())


def present_sensor_keys(sensors: object) -> list[str]:
    if not isinstance(sensors, dict):
        return []
    return [key for key in SENSOR_KEYS if sensors.get(key) is not None]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only P0 readiness check for the deployed ESP32 relay demo."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument(
        "--max-age-seconds",
        type=float,
        default=20.0,
        help="Maximum accepted age of the latest ESP32 heartbeat or telemetry (default: 20).",
    )
    parser.add_argument(
        "--min-sensor-count",
        type=int,
        default=2,
        help="Minimum number of present real-sensor fields (default: 2).",
    )
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds (default: 20).")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print one concise status line instead of the full JSON report.",
    )
    args = parser.parse_args()

    if args.max_age_seconds < 0:
        parser.error("--max-age-seconds must be non-negative")
    if args.min_sensor_count < 1:
        parser.error("--min-sensor-count must be at least 1")

    base_url = args.base_url.rstrip("/")
    try:
        health = request_json(f"{base_url}/api/health", args.timeout)
        state = request_json(f"{base_url}/api/state/{args.device_id}", args.timeout)
        diagnostics = request_json(
            f"{base_url}/api/realtime/diagnostics/{args.device_id}", args.timeout
        )
    except urllib.error.HTTPError as exc:
        error = (
            "HTTP 429: public rate limit active; stop repeated refreshes and retry after cooldown"
            if exc.code == 429
            else str(exc)
        )
        if args.compact:
            print(f"verdict=ERROR error={error}")
        else:
            print(json.dumps({"verdict": "ERROR", "read_only": True, "error": error}, ensure_ascii=False, indent=2))
        return 1
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        if args.compact:
            print(f"verdict=ERROR error={exc}")
        else:
            print(json.dumps({"verdict": "ERROR", "read_only": True, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    now = datetime.now(timezone.utc)
    diagnostic_state = diagnostics.get("state") if isinstance(diagnostics, dict) else {}
    if not isinstance(diagnostic_state, dict):
        diagnostic_state = {}

    state_age = age_seconds(state.get("last_seen"), now)
    diagnostics_age = age_seconds(diagnostic_state.get("last_seen"), now)
    sensors = state.get("sensors") if isinstance(state, dict) else {}
    sensor_keys = present_sensor_keys(sensors)
    checks = {
        "cloud_ready": health.get("cloud_ready") is True,
        "persistent_storage": health.get("persistent_storage") is True,
        "device_online": state.get("online") is True,
        "websocket_session_connected": state.get("session_connected") is True,
        "uart_ok": state.get("uart_ok") is True,
        "ack_errors_clear": state.get("ack_err_count", 0) == 0,
        "action_queue_clear": state.get("pending_action_count", 0) == 0,
        "state_is_fresh": state_age is not None and state_age <= args.max_age_seconds,
        "diagnostics_is_fresh": diagnostics_age is not None and diagnostics_age <= args.max_age_seconds,
        "enough_sensor_fields": len(sensor_keys) >= args.min_sensor_count,
        "edge_id_matches": bool(state.get("edge_id")) and state.get("edge_id") == diagnostic_state.get("edge_id"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "verdict": "PASS" if not failed else "FAIL",
        "read_only": True,
        "checked_at_utc": now.isoformat().replace("+00:00", "Z"),
        "base_url": base_url,
        "device_id": args.device_id,
        "checks": checks,
        "snapshot": {
            "ai_provider": health.get("ai_provider"),
            "ai_model": health.get("ai_model"),
            "persistent_storage": health.get("persistent_storage"),
            "edge_id": state.get("edge_id"),
            "session_connected": state.get("session_connected"),
            "ack_ok_count": state.get("ack_ok_count"),
            "ack_err_count": state.get("ack_err_count"),
            "pending_action_count": state.get("pending_action_count"),
            "state_last_seen": state.get("last_seen"),
            "diagnostics_last_seen": diagnostic_state.get("last_seen"),
            "state_age_seconds": round(state_age, 1) if state_age is not None else None,
            "diagnostics_age_seconds": round(diagnostics_age, 1) if diagnostics_age is not None else None,
            "sensor_keys": sensor_keys,
            "sensors": {key: sensors.get(key) for key in sensor_keys} if isinstance(sensors, dict) else {},
        },
        "failed_checks": failed,
    }
    if args.compact:
        failed_text = ",".join(failed) if failed else "-"
        state_age_text = f"{state_age:.1f}s" if state_age is not None else "unknown"
        diagnostics_age_text = (
            f"{diagnostics_age:.1f}s" if diagnostics_age is not None else "unknown"
        )
        print(
            f"verdict={result['verdict']} "
            f"state_age={state_age_text} "
            f"diagnostics_age={diagnostics_age_text} "
            f"failed={failed_text}"
        )
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
