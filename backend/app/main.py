from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .ai import get_ai_client
from .asr import get_asr_client
from .config import Settings, get_settings
from .schemas import (
    AckRequest,
    AckResponse,
    AsrRecognizeRequest,
    AsrRecognizeResponse,
    AsrTranscribeResponse,
    ActionSpec,
    ChatRequest,
    ChatResponse,
    CommandsResponse,
    DeviceRunState,
    DiagnosticsResponse,
    HardwareActionRequest,
    HardwareActionResponse,
    HealthResponse,
    HeartbeatRequest,
    RealtimeInjectRequest,
    RealtimeStatusResponse,
    RfidRegisterRequest,
    RfidRegisterResponse,
    RfidScanRequest,
    RfidScanResponse,
    TelemetryRequest,
)
from .store import RuntimeStore
from .realtime import ConnectionManager


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = RuntimeStore(
        settings.device_id,
        settings.edge_id,
        rfid_registry_path=settings.rfid_registry_path,
    )
    manager = ConnectionManager(store)
    ai_client = get_ai_client(settings)
    asr_client = get_asr_client(settings)

    app = FastAPI(title=settings.app_name)
    app.state.settings = settings
    app.state.store = store
    app.state.realtime = manager
    app.state.ai = ai_client
    app.state.asr = asr_client

    def require_control_token(x_demo_token: str | None = Header(default=None)) -> None:
        if settings.control_token and x_demo_token != settings.control_token:
            raise HTTPException(status_code=401, detail="control token required")

    async def emit_state(device_id: str, state: DeviceRunState, **extra: Any) -> None:
        store.set_state(device_id, state, online=True)
        await manager.broadcast(device_id, {"type": "state", "state": state.value, **extra})

    async def run_text_turn(device_id: str, text: str, source: str) -> ChatResponse:
        device = store.ensure_device(device_id)
        await emit_state(device.device_id, DeviceRunState.think, stage="agent")
        plan = await ai_client.plan(text, device)
        store.note_text_turn(device.device_id, text, plan.reply, plan.speech, source=source)
        actions = store.enqueue_actions(device.device_id, plan.actions)
        commands = [action.wrapped_line for action in actions]

        await manager.broadcast(
            device.device_id,
            {"type": "assistant", "text": plan.reply, "speech": plan.speech, "source": source},
        )
        delivered = await manager.broadcast(device.device_id, {"type": "stm32/commands", "lines": commands})
        if delivered:
            store.mark_actions_sent([action.id for action in actions])
        await emit_state(device.device_id, DeviceRunState.idle)
        final_state = store.ensure_device(device.device_id)
        return ChatResponse(
            device_id=device.device_id,
            user_text=text,
            reply=plan.reply,
            speech=plan.speech,
            actions=actions,
            commands=commands,
            state=final_state,
        )

    async def handle_asr_audio_upload(
        *,
        content: bytes,
        filename: str,
        content_type: str,
        device_id: str,
        mock_text: str,
        inject: bool,
        source: str,
        audio_format: str,
        sample_rate: int | None,
        channels: int | None,
    ) -> AsrTranscribeResponse:
        if not content:
            raise HTTPException(status_code=400, detail="audio file cannot be empty")

        audio_dir = Path(__file__).resolve().parents[1] / "data" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename or "audio.wav").suffix or ".wav"
        safe_suffix = suffix if len(suffix) <= 8 else ".wav"
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        audio_path = audio_dir / f"{stamp}-{uuid4().hex[:10]}{safe_suffix}"
        audio_path.write_bytes(content)

        text = mock_text.strip()
        provider = "mock_text" if text else settings.asr_provider
        error = None
        ok = bool(text)
        if not text:
            try:
                result = await app.state.asr.transcribe(
                    content,
                    filename=filename,
                    content_type=content_type,
                    audio_format=audio_format,
                    sample_rate=sample_rate,
                    channels=channels,
                    audio_path=str(audio_path),
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            text = result.text
            ok = result.ok
            provider = result.provider
            error = result.error
        state = store.note_asr_result(
            device_id,
            text=text,
            audio_bytes=len(content),
            audio_path=str(audio_path),
            ok=ok,
            provider=provider,
            error=error,
            hardware_seen=source.startswith("esp32"),
        )
        await manager.broadcast(
            state.device_id,
            {
                "type": "asr/result",
                "ok": ok,
                "provider": provider,
                "text": text,
                "error": error,
                "audio_bytes": len(content),
                "source": source,
                "state": state.model_dump(mode="json"),
            },
        )

        chat_result = None
        if ok and inject:
            chat_result = await run_text_turn(state.device_id, text, source)
            state = chat_result.state

        return AsrTranscribeResponse(
            ok=ok,
            provider=provider,
            device_id=state.device_id,
            text=text,
            source=source,
            audio_bytes=len(content),
            audio_path=str(audio_path),
            state=state,
            chat=chat_result,
            error=error,
        )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        configured_provider = settings.ai_provider.lower()
        cloud_ready = configured_provider == "dashscope_openai" and bool(settings.dashscope_api_key)
        provider = "dashscope_openai" if cloud_ready else "mock"
        return HealthResponse(
            status="ok",
            protocol=settings.protocol,
            ai_provider=provider,
            ai_model=settings.ai_model if cloud_ready else "local-rules",
            cloud_ready=cloud_ready,
            device_id=settings.device_id,
            edge_id=settings.edge_id,
        )

    @app.get("/api/state/{device_id}")
    def get_state(device_id: str):
        return store.ensure_device(device_id)

    @app.post("/api/hardware/telemetry")
    async def hardware_telemetry(payload: TelemetryRequest):
        state = store.telemetry(
            payload.device_id,
            edge_id=payload.edge_id,
            sensors=payload.sensors,
            voice_state=payload.voice_state,
        )
        await manager.broadcast(state.device_id, {"type": "telemetry", "state": state.model_dump(mode="json")})
        return state

    @app.post("/api/hardware/heartbeat")
    async def hardware_heartbeat(payload: HeartbeatRequest):
        state = store.heartbeat(
            payload.device_id,
            edge_id=payload.edge_id,
            online=payload.online,
            uart_ok=payload.uart_ok,
            voice_state=payload.voice_state,
            uptime_ms=payload.uptime_ms,
        )
        await manager.broadcast(state.device_id, {"type": "heartbeat", "state": state.model_dump(mode="json")})
        return state

    @app.get("/api/hardware/commands/{device_id}", response_model=CommandsResponse)
    def hardware_commands(device_id: str) -> CommandsResponse:
        actions = store.pending_commands(device_id, mark_sent=True)
        return CommandsResponse(
            device_id=device_id,
            commands=[action.wrapped_line for action in actions],
            actions=actions,
        )

    @app.post("/api/hardware/action", response_model=HardwareActionResponse)
    async def hardware_action(payload: HardwareActionRequest, _auth: None = Depends(require_control_token)) -> HardwareActionResponse:
        try:
            actions = store.enqueue_actions(
                payload.device_id or settings.device_id,
                [ActionSpec(type=payload.type, payload=payload.payload)],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state = store.ensure_device(payload.device_id or settings.device_id)
        delivered = await manager.broadcast(
            state.device_id,
            {"type": "stm32/commands", "lines": [action.wrapped_line for action in actions]},
        )
        if payload.mark_sent and delivered:
            store.mark_actions_sent([action.id for action in actions])
            state = store.ensure_device(payload.device_id or settings.device_id)
        return HardwareActionResponse(
            device_id=state.device_id,
            actions=actions,
            commands=[action.wrapped_line for action in actions],
            state=state,
        )

    @app.post("/api/hardware/ack", response_model=AckResponse)
    async def hardware_ack(payload: AckRequest) -> AckResponse:
        try:
            action, state, ok = store.ack(
                device_id=payload.device_id,
                action_id=payload.action_id,
                ok=payload.ok,
                line=payload.line,
                error=payload.error,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown action_id: {exc.args[0]}") from exc
        await manager.broadcast(
            state.device_id,
            {"type": "ack", "action_id": action.id, "ok": ok, "state": state.model_dump(mode="json")},
        )
        return AckResponse(device_id=state.device_id, action_id=action.id, ok=ok, action=action, state=state)

    @app.post("/api/rfid/register", response_model=RfidRegisterResponse)
    async def rfid_register(payload: RfidRegisterRequest, _auth: None = Depends(require_control_token)) -> RfidRegisterResponse:
        try:
            user, state = store.register_rfid(payload.uid, payload.name, payload.mode, payload.device_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await manager.broadcast(
            state.device_id,
            {"type": "rfid/user", "user": user.model_dump(mode="json"), "state": state.model_dump(mode="json")},
        )
        return RfidRegisterResponse(user=user, state=state)

    @app.post("/api/rfid/scan", response_model=RfidScanResponse)
    async def rfid_scan(payload: RfidScanRequest, _auth: None = Depends(require_control_token)) -> RfidScanResponse:
        try:
            uid, user, state = store.scan_rfid(payload.uid, payload.device_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if user:
            message = f"已解锁，{user.name}，{user.mode.value} 模式。"
            specs = [
                ActionSpec(type="tts_speak", payload={"text": message}),
                ActionSpec(type="oled_display", payload={"text": f"{user.mode.value.upper()} MODE"}),
                ActionSpec(type="lock_control", payload={"state": "off"}),
            ]
        else:
            message = "未注册卡，已拒绝。"
            specs = [
                ActionSpec(type="tts_speak", payload={"text": message}),
                ActionSpec(type="oled_display", payload={"text": "CARD DENIED"}),
                ActionSpec(type="lock_control", payload={"state": "on"}),
            ]

        actions = store.enqueue_actions(state.device_id, specs)
        commands = [action.wrapped_line for action in actions]
        await manager.broadcast(
            state.device_id,
            {
                "type": "rfid/scan",
                "uid": uid,
                "authorized": bool(user),
                "user": user.model_dump(mode="json") if user else None,
                "state": state.model_dump(mode="json"),
            },
        )
        delivered = await manager.broadcast(state.device_id, {"type": "stm32/commands", "lines": commands})
        if delivered:
            store.mark_actions_sent([action.id for action in actions])
        return RfidScanResponse(
            uid=uid,
            authorized=bool(user),
            message=message,
            user=user,
            state=store.ensure_device(state.device_id),
            actions=actions,
            commands=commands,
        )

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, _auth: None = Depends(require_control_token)) -> ChatResponse:
        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text cannot be empty")
        return await run_text_turn(payload.device_id or settings.device_id, text, payload.source)

    @app.post("/api/asr/transcribe", response_model=AsrTranscribeResponse)
    async def asr_transcribe(
        audio: UploadFile = File(...),
        device_id: str = Form(settings.device_id),
        mock_text: str = Form(""),
        inject: bool = Form(False),
        source: str = Form("asr_upload"),
        audio_format: str = Form(""),
        sample_rate: int | None = Form(None),
        channels: int | None = Form(None),
        _auth: None = Depends(require_control_token),
    ) -> AsrTranscribeResponse:
        content = await audio.read()
        return await handle_asr_audio_upload(
            content=content,
            filename=audio.filename or "",
            content_type=audio.content_type or "",
            device_id=device_id,
            mock_text=mock_text,
            inject=inject,
            source=source,
            audio_format=audio_format,
            sample_rate=sample_rate,
            channels=channels,
        )

    @app.post("/api/asr/transcribe/chunk")
    async def asr_transcribe_chunk(
        chunk: UploadFile = File(...),
        upload_id: str = Form(...),
        offset: int = Form(...),
        total_size: int = Form(...),
        final: bool = Form(False),
        device_id: str = Form(settings.device_id),
        inject: bool = Form(False),
        source: str = Form("esp32_mic_chunked"),
        audio_format: str = Form(""),
        sample_rate: int | None = Form(None),
        channels: int | None = Form(None),
    ) -> dict[str, Any] | AsrTranscribeResponse:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", upload_id):
            raise HTTPException(status_code=400, detail="invalid upload_id")
        if offset < 0 or total_size <= 0:
            raise HTTPException(status_code=400, detail="invalid upload offset or size")

        content = await chunk.read()
        if not content:
            raise HTTPException(status_code=400, detail="chunk cannot be empty")
        if offset + len(content) > total_size:
            raise HTTPException(status_code=400, detail="chunk exceeds declared total size")

        chunk_dir = Path(__file__).resolve().parents[1] / "data" / "audio_chunks"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        part_path = chunk_dir / f"{upload_id}.part"
        received = part_path.stat().st_size if part_path.exists() else 0

        if offset < received:
            if offset + len(content) <= received:
                return {"ok": True, "complete": False, "received": received}
            return {
                "ok": False,
                "complete": False,
                "received": received,
                "error": f"overlapping chunk at {offset}, expected {received}",
            }
        if offset > received:
            return {
                "ok": False,
                "complete": False,
                "received": received,
                "error": f"offset mismatch: got {offset}, expected {received}",
            }

        with part_path.open("ab") as part_file:
            part_file.write(content)
        received += len(content)

        if not final:
            return {"ok": True, "complete": False, "received": received}
        if received != total_size:
            return {
                "ok": False,
                "complete": False,
                "received": received,
                "error": f"incomplete upload: received {received}, expected {total_size}",
            }

        assembled = part_path.read_bytes()
        part_path.unlink(missing_ok=True)
        return await handle_asr_audio_upload(
            content=assembled,
            filename="esp32-mic.wav",
            content_type=chunk.content_type or "audio/wav",
            device_id=device_id,
            mock_text="",
            inject=inject,
            source=source,
            audio_format=audio_format,
            sample_rate=sample_rate,
            channels=channels,
        )

    @app.post("/api/asr/recognized", response_model=AsrRecognizeResponse)
    async def asr_recognized(payload: AsrRecognizeRequest, _auth: None = Depends(require_control_token)) -> AsrRecognizeResponse:
        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text cannot be empty")

        state = store.note_asr_result(
            payload.device_id or settings.device_id,
            text=text,
            audio_bytes=0,
            audio_path="",
            ok=True,
            provider="client_speech",
        )
        await manager.broadcast(
            state.device_id,
            {
                "type": "asr/result",
                "ok": True,
                "text": text,
                "audio_bytes": 0,
                "source": payload.source,
                "state": state.model_dump(mode="json"),
            },
        )

        chat_result = None
        if payload.inject:
            chat_result = await run_text_turn(state.device_id, text, payload.source)
            state = chat_result.state

        return AsrRecognizeResponse(
            ok=True,
            provider="client_speech",
            device_id=state.device_id,
            text=text,
            source=payload.source,
            state=state,
            chat=chat_result,
        )

    @app.post("/api/realtime/inject", response_model=ChatResponse)
    async def realtime_inject(payload: RealtimeInjectRequest, _auth: None = Depends(require_control_token)) -> ChatResponse:
        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text cannot be empty")
        return await run_text_turn(payload.device_id or settings.device_id, text, payload.source)

    @app.get("/api/realtime/status", response_model=RealtimeStatusResponse)
    def realtime_status() -> RealtimeStatusResponse:
        return RealtimeStatusResponse(
            protocol=settings.protocol,
            connection_count=manager.connection_count(),
            devices=store.list_devices(),
        )

    @app.get("/api/realtime/diagnostics/{device_id}", response_model=DiagnosticsResponse)
    def realtime_diagnostics(device_id: str) -> DiagnosticsResponse:
        state, queued, sent, recent = store.diagnostics(device_id)
        return DiagnosticsResponse(state=state, queued_actions=queued, sent_actions=sent, recent_actions=recent)

    @app.get("/", include_in_schema=False)
    def root() -> HTMLResponse:
        return console()

    @app.get("/console", include_in_schema=False)
    def console() -> HTMLResponse:
        html = Path(__file__).with_name("static").joinpath("console.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.get("/mobile", include_in_schema=False)
    def mobile() -> HTMLResponse:
        return console()

    @app.websocket("/api/realtime/ws")
    async def realtime_ws(websocket: WebSocket, device_id: str = settings.device_id, edge_id: str | None = None):
        track_device_session = edge_id == settings.edge_id
        await manager.connect(websocket, device_id, edge_id, track_device_session=track_device_session)
        try:
            await websocket.send_json(
                {
                    "type": "hello",
                    "protocol": settings.protocol,
                    "device_id": device_id,
                    "edge_id": edge_id,
                }
            )
            while True:
                message = await websocket.receive_text()
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "message": "message must be JSON"})
                    continue
                await handle_ws_message(websocket, payload, device_id)
        except WebSocketDisconnect:
            await manager.disconnect(websocket, device_id, edge_id, track_device_session=track_device_session)

    async def handle_ws_message(websocket: WebSocket, payload: dict[str, Any], device_id: str) -> None:
        message_type = payload.get("type")
        if message_type == "ping":
            await websocket.send_json({"type": "pong"})
            return

        if message_type == "wake":
            store.set_state(device_id, DeviceRunState.listen, online=True)
            await websocket.send_json({"type": "state", "state": "listen"})
            await websocket.send_json({"type": "speak", "text": "请说话"})
            actions = store.enqueue_actions(device_id, [ActionSpec(type="tts_speak", payload={"text": "请说话"})])
            store.mark_actions_sent([action.id for action in actions])
            await websocket.send_json({"type": "stm32/commands", "lines": [action.wrapped_line for action in actions]})
            return

        if message_type == "text":
            text = str(payload.get("text", "")).strip()
            if not text:
                await websocket.send_json({"type": "error", "message": "text cannot be empty"})
                return
            await run_text_turn(device_id, text, "websocket")
            return

        if message_type == "tools/list":
            await websocket.send_json(
                {
                    "type": "tools/list",
                    "tools": [
                        "tts_speak",
                        "volume_control",
                        "oled_display",
                        "fan_control",
                        "buzzer_alert",
                        "buzzer_music",
                        "focus_mode",
                        "servo_action",
                        "lock_control",
                        "lamp_control",
                    ],
                }
            )
            return

        if message_type == "tools/call":
            action_name = str(payload.get("name", "")).strip()
            arguments = payload.get("arguments") or {}
            try:
                actions = store.enqueue_actions(device_id, [ActionSpec(type=action_name, payload=arguments)])
            except ValueError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                return
            store.mark_actions_sent([action.id for action in actions])
            await websocket.send_json({"type": "stm32/commands", "lines": [action.wrapped_line for action in actions]})
            return

        if message_type in {"ack", "stm32/ack"}:
            try:
                action, state, ok = store.ack(
                    device_id=device_id,
                    action_id=payload.get("action_id"),
                    ok=payload.get("ok"),
                    line=payload.get("line"),
                    error=payload.get("error"),
                )
            except (ValueError, KeyError) as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                return
            await websocket.send_json({"type": "ack", "action_id": action.id, "ok": ok, "state": state.model_dump(mode="json")})
            return

        await websocket.send_json({"type": "error", "message": f"unsupported message type: {message_type}"})

    return app


app = create_app()
