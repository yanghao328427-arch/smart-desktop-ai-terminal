from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DeviceRunState(str, Enum):
    offline = "offline"
    idle = "idle"
    listen = "listen"
    recording = "recording"
    think = "think"
    speak = "speak"
    error = "error"


class ActionStatus(str, Enum):
    queued = "queued"
    sent = "sent"
    acked = "acked"
    failed = "failed"


class UserMode(str, Enum):
    study = "study"
    rest = "rest"
    demo = "demo"
    admin = "admin"


class HealthResponse(BaseModel):
    status: str
    protocol: str
    ai_provider: str
    ai_model: str
    cloud_ready: bool
    device_id: str
    edge_id: str


class RfidUser(BaseModel):
    user_id: str
    uid: str | None = None
    name: str
    mode: UserMode
    profile_summary: str | None = None
    admin_notes: str | None = None
    registered_at: datetime
    updated_at: datetime | None = None


class DialogueTurn(BaseModel):
    role: str
    text: str
    time: datetime
    source: str | None = None


class DeviceSnapshot(BaseModel):
    device_id: str
    edge_id: str | None = None
    state: DeviceRunState = DeviceRunState.offline
    online: bool = False
    uart_ok: bool = False
    session_connected: bool = False
    voice_state: str | None = None
    last_seen: datetime | None = None
    device_last_seen: datetime | None = None
    device_age_seconds: float | None = None
    sensors: dict[str, Any] = Field(default_factory=dict)
    current_user: RfidUser | None = None
    active_session_id: str | None = None
    mode: UserMode | None = None
    last_text: str | None = None
    last_asr_text: str | None = None
    last_assistant: str | None = None
    last_speech: str | None = None
    last_commands: list[str] = Field(default_factory=list)
    recent_dialogue: list[DialogueTurn] = Field(default_factory=list)
    last_ack: dict[str, Any] | None = None
    ack_ok_count: int = 0
    ack_err_count: int = 0
    pending_action_count: int = 0


class ActionRecord(BaseModel):
    id: str
    device_id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    command: str
    wrapped_line: str
    status: ActionStatus = ActionStatus.queued
    created_at: datetime
    sent_at: datetime | None = None
    acked_at: datetime | None = None
    error: str | None = None


class ActionSpec(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class HardwareActionRequest(ActionSpec):
    device_id: str | None = None
    mark_sent: bool = True
    source: str = "web_manual"


class HardwareActionResponse(BaseModel):
    device_id: str
    actions: list[ActionRecord]
    commands: list[str]
    state: DeviceSnapshot


class TelemetryRequest(BaseModel):
    device_id: str
    edge_id: str | None = None
    sensors: dict[str, Any] = Field(default_factory=dict)
    voice_state: str | None = None


class HeartbeatRequest(BaseModel):
    device_id: str
    edge_id: str | None = None
    online: bool = True
    uart_ok: bool = False
    voice_state: str | None = None
    uptime_ms: int | None = None


class CommandsResponse(BaseModel):
    device_id: str
    commands: list[str]
    actions: list[ActionRecord]


class AckRequest(BaseModel):
    device_id: str | None = None
    action_id: str | None = None
    ok: bool | None = None
    line: str | None = None
    error: str | None = None


class AckResponse(BaseModel):
    device_id: str
    action_id: str
    ok: bool
    action: ActionRecord
    state: DeviceSnapshot


class RfidRegisterRequest(BaseModel):
    uid: str
    name: str
    mode: UserMode
    profile_summary: str | None = None
    admin_notes: str | None = None
    device_id: str | None = None


class RfidRegisterResponse(BaseModel):
    user: RfidUser
    state: DeviceSnapshot


class RfidScanRequest(BaseModel):
    uid: str
    device_id: str | None = None
    source: str = "web_simulator"


class RfidScanResponse(BaseModel):
    uid: str
    source: str
    authorized: bool
    enrolled: bool = False
    enroll_id: str | None = None
    message: str
    user: RfidUser | None = None
    state: DeviceSnapshot
    actions: list[ActionRecord]
    commands: list[str]


class UserCreateRequest(BaseModel):
    name: str
    mode: UserMode = UserMode.study
    profile_summary: str | None = None
    admin_notes: str | None = None


class UserResponse(BaseModel):
    user: RfidUser


class UsersResponse(BaseModel):
    users: list[RfidUser]


class ContextSelectRequest(BaseModel):
    user_id: str
    device_id: str | None = None


class ContextResponse(BaseModel):
    user: RfidUser
    state: DeviceSnapshot


class RfidEnrollStartRequest(BaseModel):
    user_id: str | None = None
    name: str | None = None
    mode: UserMode = UserMode.study
    profile_summary: str | None = None
    admin_notes: str | None = None
    device_id: str | None = None
    ttl_seconds: int = Field(default=60, ge=10, le=300)


class RfidEnrollStatusResponse(BaseModel):
    enroll_id: str
    status: str
    expires_at: datetime
    created_at: datetime
    completed_at: datetime | None = None
    uid: str | None = None
    user: RfidUser
    state: DeviceSnapshot | None = None


class ChatRequest(BaseModel):
    text: str
    device_id: str | None = None
    source: str = "web"
    user_id: str | None = None


class ChatResponse(BaseModel):
    device_id: str
    user_text: str
    reply: str
    speech: str
    actions: list[ActionRecord]
    commands: list[str]
    state: DeviceSnapshot


class AsrTranscribeResponse(BaseModel):
    ok: bool
    provider: str
    device_id: str
    text: str
    source: str = "asr_upload"
    audio_bytes: int
    audio_path: str
    state: DeviceSnapshot
    chat: ChatResponse | None = None
    error: str | None = None


class AsrRecognizeRequest(BaseModel):
    text: str
    device_id: str | None = None
    source: str = "browser_speech"
    inject: bool = True


class AsrRecognizeResponse(BaseModel):
    ok: bool
    provider: str
    device_id: str
    text: str
    source: str
    state: DeviceSnapshot
    chat: ChatResponse | None = None


class RealtimeInjectRequest(ChatRequest):
    source: str = "inject"


class RealtimeStatusResponse(BaseModel):
    protocol: str
    connection_count: int
    devices: list[DeviceSnapshot]


class DiagnosticsResponse(BaseModel):
    state: DeviceSnapshot
    queued_actions: list[ActionRecord]
    sent_actions: list[ActionRecord]
    recent_actions: list[ActionRecord]
