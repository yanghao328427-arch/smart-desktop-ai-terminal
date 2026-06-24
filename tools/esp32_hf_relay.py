from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from contextlib import suppress
from urllib.parse import parse_qs, unquote, urlencode

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from websockets.exceptions import ConnectionClosed, InvalidStatus


MAX_BODY_BYTES = 64 * 1024
FORWARDED_POST_PATHS = {
    "/api/hardware/telemetry",
    "/api/hardware/heartbeat",
    "/api/hardware/ack",
    "/api/rfid/scan",
}
FORWARDED_HEADERS = ("X-Device-Token",)
WS_PATH = "/api/realtime/ws"


def allowed_path(method: str, path: str) -> bool:
    if method == "POST":
        return path in FORWARDED_POST_PATHS
    if method != "GET" or not path.startswith("/api/hardware/commands/"):
        return False
    device_id = unquote(path.removeprefix("/api/hardware/commands/"))
    return bool(device_id) and "/" not in device_id


def upstream_ws_url(upstream_base: str, query_string: str) -> str:
    scheme = "wss" if upstream_base.startswith("https://") else "ws"
    host = upstream_base.split("://", 1)[1].rstrip("/")
    query = parse_qs(query_string, keep_blank_values=False)
    allowed_query = {
        key: values[-1]
        for key, values in query.items()
        if key in {"device_id", "edge_id"} and values and values[-1]
    }
    suffix = f"?{urlencode(allowed_query)}" if allowed_query else ""
    return f"{scheme}://{host}{WS_PATH}{suffix}"


def create_app(upstream_base: str, upstream_timeout: float) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    rate_limited_until = 0.0

    def rate_limit_remaining() -> int:
        return max(0, int(rate_limited_until - time.monotonic()))

    def enter_rate_limit_cooldown(seconds: int = 300) -> None:
        nonlocal rate_limited_until
        rate_limited_until = max(rate_limited_until, time.monotonic() + max(1, seconds))
        print(
            f"[relay] upstream rate limited; pausing new upstream requests for {seconds}s",
            file=sys.stderr,
            flush=True,
        )

    @app.get("/relay/health")
    async def relay_health() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "mode": "http+websocket",
                "upstream": upstream_base,
                "rate_limit_cooldown_seconds": rate_limit_remaining(),
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def forward_http(request: Request, path: str) -> Response:
        relay_path = f"/{path}"
        if request.url.query or not allowed_path(request.method, relay_path):
            return Response(
                content=b'{"detail":"unsupported relay endpoint"}',
                status_code=404,
                media_type="application/json",
            )
        cooldown = rate_limit_remaining()
        if cooldown:
            return Response(
                content=b'{"detail":"upstream rate limit cooldown"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(cooldown), "Cache-Control": "no-store"},
            )

        body = b""
        if request.method == "POST":
            body = await request.body()
            if not 1 <= len(body) <= MAX_BODY_BYTES:
                return Response(
                    content=b'{"detail":"payload is too large"}',
                    status_code=413,
                    media_type="application/json",
                )
            try:
                json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return Response(
                    content=b'{"detail":"relay only accepts JSON telemetry"}',
                    status_code=400,
                    media_type="application/json",
                )

        headers = {}
        if request.method == "POST":
            headers["Content-Type"] = "application/json"
        for header_name in FORWARDED_HEADERS:
            header_value = request.headers.get(header_name)
            if header_value:
                headers[header_name] = header_value

        try:
            async with httpx.AsyncClient(timeout=upstream_timeout, trust_env=True) as client:
                upstream = await client.request(
                    request.method,
                    f"{upstream_base}{relay_path}",
                    content=body if request.method == "POST" else None,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            print(
                f"[relay] upstream {request.method} {relay_path} failed: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return Response(
                content=b'{"detail":"upstream unavailable"}',
                status_code=502,
                media_type="application/json",
            )

        if upstream.status_code == 429:
            retry_after = upstream.headers.get("retry-after", "")
            enter_rate_limit_cooldown(int(retry_after) if retry_after.isdigit() else 300)
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json").split(";", 1)[0],
            headers={"Cache-Control": "no-store"},
        )

    @app.websocket(WS_PATH)
    async def forward_websocket(local: WebSocket) -> None:
        await local.accept()
        cooldown = rate_limit_remaining()
        if cooldown:
            await local.send_json(
                {
                    "type": "error",
                    "message": "websocket upstream rate limited",
                    "retry_after_seconds": cooldown,
                }
            )
            await local.close(code=1013)
            return
        target = upstream_ws_url(upstream_base, local.scope.get("query_string", b"").decode("ascii"))
        print(f"[relay] websocket connecting -> {target}", flush=True)
        try:
            async with websockets.connect(
                target,
                proxy=True,
                open_timeout=upstream_timeout,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_size=MAX_BODY_BYTES,
            ) as upstream:
                print("[relay] websocket connected", flush=True)

                async def local_to_upstream() -> None:
                    while True:
                        message = await local.receive_text()
                        await upstream.send(message)

                async def upstream_to_local() -> None:
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await local.send_bytes(message)
                        else:
                            await local.send_text(message)

                tasks = {
                    asyncio.create_task(local_to_upstream()),
                    asyncio.create_task(upstream_to_local()),
                }
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                for task in done:
                    with suppress(WebSocketDisconnect, ConnectionClosed, asyncio.CancelledError):
                        task.result()
                for task in pending:
                    with suppress(asyncio.CancelledError):
                        await task
        except (OSError, TimeoutError, websockets.WebSocketException) as exc:
            if isinstance(exc, InvalidStatus) and exc.response.status_code == 429:
                retry_after = exc.response.headers.get("retry-after", "")
                enter_rate_limit_cooldown(int(retry_after) if retry_after.isdigit() else 300)
            print(f"[relay] websocket upstream failed: {exc}", file=sys.stderr, flush=True)
            with suppress(RuntimeError):
                await local.send_json({"type": "error", "message": "websocket upstream unavailable"})
        finally:
            with suppress(RuntimeError):
                await local.close()
            print("[relay] websocket disconnected", flush=True)

    return app


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Relay ESP32 HTTP and WebSocket traffic from the LAN to a Hugging Face Space."
    )
    parser.add_argument("--host", default="0.0.0.0", help="LAN listen host")
    parser.add_argument("--port", type=int, default=8090, help="LAN listen port")
    parser.add_argument(
        "--upstream",
        default="http://8.163.38.158",
        help="Aliyun ECS fallback backend base URL",
    )
    parser.add_argument("--timeout", type=float, default=20.0, help="Upstream connect/request timeout")
    args = parser.parse_args()

    upstream_base = args.upstream.rstrip("/")
    if not upstream_base.startswith(("http://", "https://")):
        parser.error("--upstream must use http:// or https://")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    print(
        f"[relay] listening on http://{args.host}:{args.port} "
        f"(ws:// same port) -> {upstream_base}",
        flush=True,
    )
    uvicorn.run(
        create_app(upstream_base, args.timeout),
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
