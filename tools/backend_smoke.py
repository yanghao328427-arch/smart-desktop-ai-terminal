from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any


def request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a backend text-loop smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8083")
    parser.add_argument("--device-id", default="desktop-agent-001")
    parser.add_argument("--text", default="你是谁")
    parser.add_argument("--ack", action="store_true", help="ACK every queued command after polling it.")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    try:
        health = request_json("GET", f"{base}/api/health")
        chat = request_json("POST", f"{base}/api/chat", {"device_id": args.device_id, "text": args.text})
        commands = request_json("GET", f"{base}/api/hardware/commands/{args.device_id}")

        acked: list[dict[str, Any]] = []
        if args.ack:
            for action in commands["actions"]:
                acked.append(
                    request_json(
                        "POST",
                        f"{base}/api/hardware/ack",
                        {"device_id": args.device_id, "action_id": action["id"], "ok": True},
                    )
                )

        result = {
            "health": health,
            "reply": chat["reply"],
            "commands": commands["commands"],
            "acked": [{"action_id": item["action_id"], "ok": item["ok"]} for item in acked],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
