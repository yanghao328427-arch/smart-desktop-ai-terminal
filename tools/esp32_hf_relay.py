from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


MAX_BODY_BYTES = 64 * 1024
FORWARDED_POST_PATHS = {
    "/api/hardware/telemetry",
    "/api/hardware/heartbeat",
    "/api/hardware/ack",
    "/api/rfid/scan",
}
FORWARDED_HEADERS = ("X-Device-Token",)


def allowed_path(method: str, path: str) -> bool:
    if method == "POST":
        return path in FORWARDED_POST_PATHS
    if method != "GET" or not path.startswith("/api/hardware/commands/"):
        return False
    device_id = unquote(path.removeprefix("/api/hardware/commands/"))
    return bool(device_id) and "/" not in device_id


class RelayHandler(BaseHTTPRequestHandler):
    server_version = "SmartDesktopEsp32Relay/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[relay] {self.address_string()} {format % args}", flush=True)

    def do_GET(self) -> None:
        self.forward("GET")

    def do_POST(self) -> None:
        self.forward("POST")

    def do_OPTIONS(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "only ESP32 relay endpoints are supported")

    def forward(self, method: str) -> None:
        parsed = urlparse(self.path)
        if parsed.query or not allowed_path(method, parsed.path):
            self.send_error(HTTPStatus.NOT_FOUND, "unsupported relay endpoint")
            return

        body = b""
        if method == "POST":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
                return
            if content_length < 1 or content_length > MAX_BODY_BYTES:
                self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "payload is too large")
                return
            body = self.rfile.read(content_length)
            try:
                json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(HTTPStatus.BAD_REQUEST, "relay only accepts JSON telemetry")
                return

        upstream_url = f"{self.server.upstream_base}{parsed.path}"
        upstream_headers = {"Content-Type": "application/json"} if method == "POST" else {}
        for header_name in FORWARDED_HEADERS:
            header_value = self.headers.get(header_name)
            if header_value:
                upstream_headers[header_name] = header_value
        request = Request(
            upstream_url,
            data=body if method == "POST" else None,
            headers=upstream_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.server.upstream_timeout) as response:
                response_body = response.read()
                self.respond(response.status, response.headers.get_content_type(), response_body)
        except HTTPError as exc:
            self.respond(exc.code, exc.headers.get_content_type() if exc.headers else "application/json", exc.read())
        except (OSError, URLError) as exc:
            print(f"[relay] upstream {method} {parsed.path} failed: {exc}", file=sys.stderr, flush=True)
            self.respond(HTTPStatus.BAD_GATEWAY, "application/json", b'{"detail":"upstream unavailable"}')

    def respond(self, status: int | HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type or "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class RelayServer(ThreadingHTTPServer):
    upstream_base: str
    upstream_timeout: float


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Relay real ESP32 device traffic from a LAN HTTP endpoint to a Hugging Face Space."
    )
    parser.add_argument("--host", default="0.0.0.0", help="LAN listen host")
    parser.add_argument("--port", type=int, default=8090, help="LAN listen port")
    parser.add_argument(
        "--upstream",
        default="https://yh001399-smart-desktop-ai-terminal.hf.space",
        help="Hugging Face Space base URL",
    )
    parser.add_argument("--timeout", type=float, default=20.0, help="Upstream request timeout in seconds")
    args = parser.parse_args()

    upstream_base = args.upstream.rstrip("/")
    if not upstream_base.startswith("https://"):
        parser.error("--upstream must use https://")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    server = RelayServer((args.host, args.port), RelayHandler)
    server.upstream_base = upstream_base
    server.upstream_timeout = args.timeout
    print(f"[relay] listening on http://{args.host}:{args.port} -> {upstream_base}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
