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
    ContextResponse,
    ContextSelectRequest,
    RealtimeInjectRequest,
    RealtimeStatusResponse,
    RfidEnrollStartRequest,
    RfidEnrollStatusResponse,
    RfidRegisterRequest,
    RfidRegisterResponse,
    RfidScanRequest,
    RfidScanResponse,
    TelemetryRequest,
    UserCreateRequest,
    UserResponse,
    UsersResponse,
)
from .store import RuntimeStore
from .realtime import ConnectionManager


RFID_SPOKEN_NAME_ALIASES = {
    "student": "学生",
    "teacher": "老师",
    "admin": "管理员",
    "guest": "访客",
}


def rfid_spoken_name(name: str | None) -> str:
    value = (name or "").strip()
    if not value:
        return ""
    alias = RFID_SPOKEN_NAME_ALIASES.get(value.casefold())
    if alias:
        return alias
    if re.search(r"[\u3400-\u9fff]", value):
        return value
    return ""


def rfid_access_speech(name: str | None, *, enrolled: bool = False) -> str:
    spoken_name = rfid_spoken_name(name)
    if enrolled:
        return f"{spoken_name}，注册成功。" if spoken_name else "新卡注册成功。"
    return f"{spoken_name}，解锁成功。" if spoken_name else "解锁成功，欢迎回来。"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = RuntimeStore(
        settings.device_id,
        settings.edge_id,
        rfid_registry_path=settings.rfid_registry_path,
        context_db_path=settings.context_db_path,
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

    def control_token_ok(x_demo_token: str | None) -> bool:
        if not settings.control_token:
            return True
        if x_demo_token and x_demo_token != settings.control_token:
            raise HTTPException(status_code=401, detail="control token required")
        return x_demo_token == settings.control_token

    def require_control_token(x_demo_token: str | None = Header(default=None)) -> None:
        if not control_token_ok(x_demo_token):
            raise HTTPException(status_code=401, detail="control token required")

    def require_control_or_device_token(
        x_demo_token: str | None = Header(default=None),
        x_device_token: str | None = Header(default=None),
    ) -> None:
        if control_token_ok(x_demo_token):
            return
        if settings.device_token and x_device_token == settings.device_token:
            return
        if not settings.control_token and not settings.device_token:
            return
        raise HTTPException(status_code=401, detail="control or device token required")

    def ensure_user_or_control_context(device_id: str, x_demo_token: str | None, user_id: str | None = None) -> bool:
        if control_token_ok(x_demo_token):
            if user_id:
                store.select_user_context(device_id, user_id, source="control_select")
            return True
        device = store.ensure_device(device_id)
        if (
            device.current_user
            and device.active_session_id
            and device.sensors.get("active_context_physical_card") is True
        ):
            return False
        raise HTTPException(status_code=403, detail="registered RFID card or control token required")

    def rfid_control_context(source: str, user: Any | None) -> tuple[str, int]:
        source_value = (source or "rc522").strip()
        if source_value == "web_simulator":
            return "web_simulator", 100
        if user is None:
            return "rfid_denied", 80
        if getattr(user.mode, "value", user.mode) == "admin":
            return "rfid_admin", 70
        return "rfid_authorized", 60

    def user_context_action(user: Any | None, uid: str | None = None, mode: str | None = None) -> ActionSpec:
        if user is None:
            return ActionSpec(type="user_context", payload={"user_id": "-", "uid": uid or "-", "mode": mode or "NONE"})
        return ActionSpec(
            type="user_context",
            payload={
                "user_id": user.user_id,
                "uid": uid or getattr(user, "uid", None) or "-",
                "mode": getattr(getattr(user, "mode", None), "value", getattr(user, "mode", mode or "NONE")),
            },
        )

    async def dispatch_actions(
        device_id: str,
        specs: list[ActionSpec],
        *,
        control_source: str,
        control_priority: int,
    ):
        actions = store.enqueue_actions(
            device_id,
            specs,
            control_source=control_source,
            control_priority=control_priority,
        )
        commands = [action.wrapped_line for action in actions]
        delivered = await manager.broadcast(device_id, {"type": "stm32/commands", "lines": commands})
        if delivered:
            store.mark_actions_sent([action.id for action in actions])
        return actions, commands, delivered

    async def handle_button_event(device_id: str, line: str, source: str = "stm32") -> tuple[Any, list[Any], list[str]]:
        clean_line = (line or "").strip()
        if not clean_line.startswith("BT:BTN:"):
            raise ValueError("button line must start with BT:BTN:")
        state = store.note_button_event(device_id, clean_line, source=source)
        await manager.broadcast(
            state.device_id,
            {
                "type": "button",
                "line": clean_line,
                "source": source,
                "state": state.model_dump(mode="json"),
            },
        )

        event = clean_line.removeprefix("BT:BTN:")
        actions: list[Any] = []
        commands: list[str] = []
        if event.startswith("KEY2:DOWN") or event.startswith("KEY2:SHORT"):
            state = store.interrupt_output(state.device_id, reason=event[:40])
            actions, commands, _ = await dispatch_actions(
                state.device_id,
                [ActionSpec(type="audio_stop", payload={"reason": event})],
                control_source="button_interrupt",
                control_priority=100,
            )
            await manager.broadcast(
                state.device_id,
                {
                    "type": "interrupt",
                    "reason": event,
                    "state": store.ensure_device(state.device_id).model_dump(mode="json"),
                },
            )
        return store.ensure_device(state.device_id), actions, commands

    def enrollment_response(record: Any, state: Any | None = None) -> RfidEnrollStatusResponse:
        return RfidEnrollStatusResponse(
            enroll_id=record.enroll_id,
            status=record.status,
            expires_at=record.expires_at,
            created_at=record.created_at,
            completed_at=record.completed_at,
            uid=record.uid,
            user=record.user,
            state=state,
        )

    async def emit_state(device_id: str, state: DeviceRunState, **extra: Any) -> None:
        store.set_state(device_id, state, online=True)
        await manager.broadcast(device_id, {"type": "state", "state": state.value, **extra})

    async def run_text_turn(device_id: str, text: str, source: str) -> ChatResponse:
        device = store.ensure_device(device_id)
        interrupt_seq = store.interrupt_seq(device.device_id)
        await emit_state(device.device_id, DeviceRunState.think, stage="agent")
        plan = await ai_client.plan(text, device)
        if store.interrupt_seq(device.device_id) != interrupt_seq:
            state = store.ensure_device(device.device_id)
            return ChatResponse(
                device_id=device.device_id,
                user_text=text,
                reply="已打断上一轮输出。",
                speech="",
                actions=[],
                commands=[],
                state=state,
            )
        store.note_text_turn(device.device_id, text, plan.reply, plan.speech, source=source)
        actions = store.enqueue_actions(device.device_id, plan.actions, control_source="ai_chat", control_priority=40)
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

    @app.get("/api/users", response_model=UsersResponse)
    def users(_auth: None = Depends(require_control_token)) -> UsersResponse:
        return UsersResponse(users=store.list_users())

    @app.post("/api/users", response_model=UserResponse)
    def create_user(payload: UserCreateRequest, _auth: None = Depends(require_control_token)) -> UserResponse:
        user = store.create_user(
            payload.name,
            payload.mode,
            profile_summary=payload.profile_summary,
            admin_notes=payload.admin_notes,
        )
        return UserResponse(user=user)

    @app.post("/api/context/select", response_model=ContextResponse)
    async def context_select(payload: ContextSelectRequest, _auth: None = Depends(require_control_token)) -> ContextResponse:
        try:
            user, state = store.select_user_context(payload.device_id or settings.device_id, payload.user_id, source="control_select")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown user_id: {exc.args[0]}") from exc
        await dispatch_actions(
            state.device_id,
            [user_context_action(user)],
            control_source="control_select",
            control_priority=100,
        )
        return ContextResponse(user=user, state=store.ensure_device(state.device_id))

    @app.post("/api/rfid/enroll/start", response_model=RfidEnrollStatusResponse)
    def rfid_enroll_start(payload: RfidEnrollStartRequest, _auth: None = Depends(require_control_token)) -> RfidEnrollStatusResponse:
        try:
            record = store.start_rfid_enrollment(
                device_id=payload.device_id or settings.device_id,
                user_id=payload.user_id,
                name=payload.name,
                mode=payload.mode,
                profile_summary=payload.profile_summary,
                admin_notes=payload.admin_notes,
                ttl_seconds=payload.ttl_seconds,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown user_id: {exc.args[0]}") from exc
        return enrollment_response(record)

    @app.get("/api/rfid/enroll/{enroll_id}", response_model=RfidEnrollStatusResponse)
    def rfid_enroll_status(enroll_id: str, _auth: None = Depends(require_control_token)) -> RfidEnrollStatusResponse:
        record = store.rfid_enrollment_status(enroll_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"unknown enroll_id: {enroll_id}")
        return enrollment_response(record, store.ensure_device(settings.device_id))

    @app.post("/api/rfid/enroll/{enroll_id}/cancel", response_model=RfidEnrollStatusResponse)
    def rfid_enroll_cancel(enroll_id: str, _auth: None = Depends(require_control_token)) -> RfidEnrollStatusResponse:
        record = store.cancel_rfid_enrollment(enroll_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"unknown enroll_id: {enroll_id}")
        return enrollment_response(record, store.ensure_device(settings.device_id))

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
    async def hardware_action(
        payload: HardwareActionRequest,
        x_demo_token: str | None = Header(default=None),
    ) -> HardwareActionResponse:
        is_control = ensure_user_or_control_context(payload.device_id or settings.device_id, x_demo_token)
        try:
            actions = store.enqueue_actions(
                payload.device_id or settings.device_id,
                [ActionSpec(type=payload.type, payload=payload.payload)],
                control_source=payload.source if is_control else "rfid_user",
                control_priority=100 if is_control else 50,
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

    @app.post("/api/hardware/button")
    async def hardware_button(
        payload: dict[str, Any],
        _auth: None = Depends(require_control_or_device_token),
    ) -> dict[str, Any]:
        device_id = str(payload.get("device_id") or settings.device_id)
        line = str(payload.get("line") or payload.get("event") or "").strip()
        if line and not line.startswith("BT:BTN:"):
            line = f"BT:BTN:{line}"
        try:
            state, actions, commands = await handle_button_event(
                device_id,
                line,
                source=str(payload.get("source") or "http"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "device_id": state.device_id,
            "line": line,
            "actions": [action.model_dump(mode="json") for action in actions],
            "commands": commands,
            "state": state.model_dump(mode="json"),
        }

    @app.post("/api/rfid/register", response_model=RfidRegisterResponse)
    async def rfid_register(payload: RfidRegisterRequest, _auth: None = Depends(require_control_token)) -> RfidRegisterResponse:
        try:
            user, state = store.register_rfid(
                payload.uid,
                payload.name,
                payload.mode,
                payload.device_id,
                profile_summary=payload.profile_summary,
                admin_notes=payload.admin_notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await dispatch_actions(
            state.device_id,
            [user_context_action(user, uid=user.uid)],
            control_source="rfid_register",
            control_priority=100,
        )
        await manager.broadcast(
            state.device_id,
            {
                "type": "rfid/user",
                "user": user.model_dump(mode="json"),
                "state": store.ensure_device(state.device_id).model_dump(mode="json"),
            },
        )
        return RfidRegisterResponse(user=user, state=store.ensure_device(state.device_id))

    @app.post("/api/rfid/scan", response_model=RfidScanResponse)
    async def rfid_scan(
        payload: RfidScanRequest,
        _auth: None = Depends(require_control_or_device_token),
    ) -> RfidScanResponse:
        try:
            scan = store.scan_rfid(payload.uid, payload.device_id, payload.source)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        uid, user, state = scan.uid, scan.user, scan.state

        if user and scan.enrolled:
            message = f"新卡已注册，{user.name}，{user.mode.value} 模式。"
            specs = [
                user_context_action(user, uid=uid),
                ActionSpec(type="oled_display", payload={"text": "CARD ENROLLED"}),
                ActionSpec(type="lock_control", payload={"state": "off"}),
                ActionSpec(type="tts_speak", payload={"text": rfid_access_speech(user.name, enrolled=True)}),
            ]
        elif user:
            message = f"已解锁，{user.name}，{user.mode.value} 模式。"
            specs = [
                user_context_action(user, uid=uid),
                ActionSpec(type="oled_display", payload={"text": f"{user.mode.value.upper()} MODE"}),
                ActionSpec(type="lock_control", payload={"state": "off"}),
                ActionSpec(type="tts_speak", payload={"text": rfid_access_speech(user.name)}),
            ]
        else:
            message = "未注册卡，已拒绝。"
            specs = [
                user_context_action(None, uid=uid, mode="DENIED"),
                ActionSpec(type="oled_display", payload={"text": "CARD DENIED"}),
                ActionSpec(type="lock_control", payload={"state": "on"}),
                ActionSpec(type="tts_speak", payload={"text": message}),
            ]

        control_source, control_priority = rfid_control_context(payload.source, user)
        actions = store.enqueue_actions(
            state.device_id,
            specs,
            control_source=control_source,
            control_priority=control_priority,
        )
        commands = [action.wrapped_line for action in actions]
        await manager.broadcast(
            state.device_id,
            {
                "type": "rfid/scan",
                "uid": uid,
                "source": payload.source,
                "authorized": bool(user),
                "enrolled": scan.enrolled,
                "enroll_id": scan.enroll_id,
                "user": user.model_dump(mode="json") if user else None,
                "state": state.model_dump(mode="json"),
            },
        )
        delivered = await manager.broadcast(state.device_id, {"type": "stm32/commands", "lines": commands})
        if delivered:
            store.mark_actions_sent([action.id for action in actions])
        return RfidScanResponse(
            uid=uid,
            source=payload.source,
            authorized=bool(user),
            enrolled=scan.enrolled,
            enroll_id=scan.enroll_id,
            message=message,
            user=user,
            state=store.ensure_device(state.device_id),
            actions=actions,
            commands=commands,
        )

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, x_demo_token: str | None = Header(default=None)) -> ChatResponse:
        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text cannot be empty")
        ensure_user_or_control_context(payload.device_id or settings.device_id, x_demo_token, payload.user_id)
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
        x_demo_token: str | None = Header(default=None),
    ) -> AsrTranscribeResponse:
        ensure_user_or_control_context(device_id, x_demo_token)
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
        x_demo_token: str | None = Header(default=None),
    ) -> dict[str, Any] | AsrTranscribeResponse:
        if inject:
            ensure_user_or_control_context(device_id, x_demo_token)
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
    async def asr_recognized(
        payload: AsrRecognizeRequest,
        x_demo_token: str | None = Header(default=None),
    ) -> AsrRecognizeResponse:
        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text cannot be empty")
        ensure_user_or_control_context(payload.device_id or settings.device_id, x_demo_token)

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
    async def realtime_inject(
        payload: RealtimeInjectRequest,
        x_demo_token: str | None = Header(default=None),
    ) -> ChatResponse:
        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text cannot be empty")
        ensure_user_or_control_context(payload.device_id or settings.device_id, x_demo_token, payload.user_id)
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

        if message_type == "button":
            line = str(payload.get("line") or payload.get("event") or "").strip()
            if line and not line.startswith("BT:BTN:"):
                line = f"BT:BTN:{line}"
            try:
                state, actions, commands = await handle_button_event(
                    device_id,
                    line,
                    source=str(payload.get("source") or "websocket"),
                )
            except ValueError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                return
            await websocket.send_json(
                {
                    "type": "button/ack",
                    "line": line,
                    "commands": commands,
                    "actions": [action.model_dump(mode="json") for action in actions],
                    "state": state.model_dump(mode="json"),
                }
            )
            return

        if message_type == "text":
            text = str(payload.get("text", "")).strip()
            if not text:
                await websocket.send_json({"type": "error", "message": "text cannot be empty"})
                return
            device = store.ensure_device(device_id)
            if not device.current_user or not device.active_session_id:
                await websocket.send_json({"type": "error", "message": "registered RFID card required"})
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
            device = store.ensure_device(device_id)
            if not device.current_user or not device.active_session_id:
                await websocket.send_json({"type": "error", "message": "registered RFID card required"})
                return
            action_name = str(payload.get("name", "")).strip()
            arguments = payload.get("arguments") or {}
            try:
                actions = store.enqueue_actions(
                    device_id,
                    [ActionSpec(type=action_name, payload=arguments)],
                    control_source="websocket_tool",
                    control_priority=40,
                )
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
