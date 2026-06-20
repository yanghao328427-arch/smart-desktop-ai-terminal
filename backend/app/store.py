from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from .actions import command_from_action, parse_ack_line, wrap_command
from .schemas import (
    ActionRecord,
    ActionSpec,
    ActionStatus,
    DeviceRunState,
    DeviceSnapshot,
    DialogueTurn,
    RfidUser,
    UserMode,
)


def now_utc() -> datetime:
    return datetime.now(UTC)


def normalize_uid(uid: str) -> str:
    return uid.strip().upper().replace(" ", "").replace(":", "").replace("-", "")


def uart_safe_action_order(specs: list[ActionSpec]) -> list[ActionSpec]:
    return [spec for spec in specs if spec.type != "tts_speak"] + [spec for spec in specs if spec.type == "tts_speak"]


class RuntimeStore:
    def __init__(
        self,
        default_device_id: str,
        default_edge_id: str,
        *,
        rfid_registry_path: str | Path | None = None,
    ) -> None:
        self.default_device_id = default_device_id
        self.default_edge_id = default_edge_id
        self._devices: dict[str, DeviceSnapshot] = {}
        self._actions: dict[str, list[ActionRecord]] = {}
        self._rfid_users: dict[str, RfidUser] = {}
        self._rfid_registry_path = Path(rfid_registry_path) if rfid_registry_path else None
        self._lock = RLock()
        self._load_rfid_users()
        self.ensure_device(default_device_id, default_edge_id)

    def ensure_device(self, device_id: str | None = None, edge_id: str | None = None) -> DeviceSnapshot:
        actual_device_id = device_id or self.default_device_id
        with self._lock:
            if actual_device_id not in self._devices:
                self._devices[actual_device_id] = DeviceSnapshot(
                    device_id=actual_device_id,
                    edge_id=edge_id or self.default_edge_id,
                )
                self._actions[actual_device_id] = []
            elif edge_id:
                self._devices[actual_device_id].edge_id = edge_id
            self._refresh_counts(actual_device_id)
            return self._devices[actual_device_id]

    def list_devices(self) -> list[DeviceSnapshot]:
        with self._lock:
            for device_id in list(self._devices):
                self._refresh_counts(device_id)
            return list(self._devices.values())

    def set_state(
        self,
        device_id: str | None,
        state: DeviceRunState,
        *,
        online: bool | None = None,
        edge_id: str | None = None,
    ) -> DeviceSnapshot:
        with self._lock:
            device = self.ensure_device(device_id, edge_id)
            device.state = state
            if online is not None:
                device.online = online
            device.last_seen = now_utc()
            self._refresh_counts(device.device_id)
            return device

    def set_session_connected(self, device_id: str, edge_id: str | None, connected: bool) -> DeviceSnapshot:
        with self._lock:
            device = self.ensure_device(device_id, edge_id)
            device.session_connected = connected
            device.online = connected
            device.state = DeviceRunState.idle if connected else DeviceRunState.offline
            device.last_seen = now_utc()
            self._refresh_counts(device.device_id)
            return device

    def heartbeat(
        self,
        device_id: str | None,
        *,
        edge_id: str | None,
        online: bool,
        uart_ok: bool,
        voice_state: str | None,
        uptime_ms: int | None,
    ) -> DeviceSnapshot:
        with self._lock:
            device = self.ensure_device(device_id, edge_id)
            device.online = online
            device.uart_ok = uart_ok
            device.voice_state = voice_state
            device.last_seen = now_utc()
            device.sensors["uptime_ms"] = uptime_ms
            if online and device.state == DeviceRunState.offline:
                device.state = DeviceRunState.idle
            if not online:
                device.state = DeviceRunState.offline
            self._refresh_counts(device.device_id)
            return device

    def telemetry(
        self,
        device_id: str | None,
        *,
        edge_id: str | None,
        sensors: dict[str, Any],
        voice_state: str | None,
    ) -> DeviceSnapshot:
        with self._lock:
            device = self.ensure_device(device_id, edge_id)
            if sensors.get("distance_enabled") is False:
                sensors["distance_ok"] = False
                sensors.pop("distance_cm", None)
                device.sensors.pop("distance_cm", None)
            elif sensors.get("distance_ok") is False:
                sensors.pop("distance_cm", None)
                device.sensors.pop("distance_cm", None)
            device.sensors.update(sensors)
            if voice_state is not None:
                device.voice_state = voice_state
            device.online = True
            device.last_seen = now_utc()
            if device.state == DeviceRunState.offline:
                device.state = DeviceRunState.idle
            self._refresh_counts(device.device_id)
            return device

    def register_rfid(self, uid: str, name: str, mode: UserMode, device_id: str | None) -> tuple[RfidUser, DeviceSnapshot]:
        normalized_uid = normalize_uid(uid)
        if not normalized_uid:
            raise ValueError("RFID UID cannot be empty")
        with self._lock:
            user = RfidUser(uid=normalized_uid, name=name.strip() or normalized_uid, mode=mode, registered_at=now_utc())
            self._rfid_users[normalized_uid] = user
            self._save_rfid_users()
            device = self.ensure_device(device_id)
            device.current_user = user
            device.mode = mode
            device.online = True
            if device.state == DeviceRunState.offline:
                device.state = DeviceRunState.idle
            device.last_seen = now_utc()
            self._refresh_counts(device.device_id)
            return user, device

    def scan_rfid(self, uid: str, device_id: str | None) -> tuple[str, RfidUser | None, DeviceSnapshot]:
        normalized_uid = normalize_uid(uid)
        if not normalized_uid:
            raise ValueError("RFID UID cannot be empty")
        with self._lock:
            user = self._rfid_users.get(normalized_uid)
            device = self.ensure_device(device_id)
            device.online = True
            device.last_seen = now_utc()
            device.sensors["last_rfid_uid"] = normalized_uid
            device.sensors["last_rfid_authorized"] = bool(user)
            device.sensors["last_rfid_at"] = now_utc().isoformat()
            if device.state == DeviceRunState.offline:
                device.state = DeviceRunState.idle
            if user:
                device.current_user = user
                device.mode = user.mode
            else:
                device.current_user = None
                device.mode = None
            self._refresh_counts(device.device_id)
            return normalized_uid, user, device

    def note_text_turn(
        self,
        device_id: str | None,
        text: str,
        reply: str,
        speech: str | None = None,
        source: str = "web",
    ) -> DeviceSnapshot:
        with self._lock:
            device = self.ensure_device(device_id)
            device.last_text = text
            device.last_asr_text = text
            device.last_assistant = reply
            device.last_speech = (speech or reply).strip() or None
            self._append_dialogue_turn(device, "user", text, source)
            self._append_dialogue_turn(device, "assistant", reply, source)
            device.online = True
            device.last_seen = now_utc()
            self._refresh_counts(device.device_id)
            return device

    def note_asr_result(
        self,
        device_id: str | None,
        *,
        text: str,
        audio_bytes: int,
        audio_path: str,
        ok: bool,
        provider: str | None = None,
        error: str | None = None,
    ) -> DeviceSnapshot:
        with self._lock:
            device = self.ensure_device(device_id)
            device.last_asr_text = text
            if ok:
                device.voice_state = "asr_ok"
            elif error:
                device.voice_state = "asr_error"
            else:
                device.voice_state = "asr_empty"
            device.sensors["last_audio_bytes"] = audio_bytes
            device.sensors["last_audio_path"] = audio_path
            device.sensors["last_asr_ok"] = ok
            device.sensors["last_asr_provider"] = provider
            device.sensors["last_asr_error"] = error
            device.sensors["last_asr_at"] = now_utc().isoformat()
            device.online = True
            device.last_seen = now_utc()
            self._refresh_counts(device.device_id)
            return device

    def enqueue_actions(self, device_id: str | None, specs: list[ActionSpec]) -> list[ActionRecord]:
        with self._lock:
            device = self.ensure_device(device_id)
            records: list[ActionRecord] = []
            for spec in uart_safe_action_order(specs):
                action_id = f"act_{uuid4().hex[:12]}"
                command = command_from_action(spec)
                record = ActionRecord(
                    id=action_id,
                    device_id=device.device_id,
                    type=spec.type,
                    payload=spec.payload,
                    command=command,
                    wrapped_line=wrap_command(action_id, command),
                    created_at=now_utc(),
                )
                records.append(record)
                self._actions[device.device_id].append(record)
            device.last_commands = [record.wrapped_line for record in records]
            self._refresh_counts(device.device_id)
            return records

    def pending_commands(self, device_id: str | None, *, mark_sent: bool) -> list[ActionRecord]:
        with self._lock:
            device = self.ensure_device(device_id)
            actions = [action for action in self._actions[device.device_id] if action.status == ActionStatus.queued]
            if mark_sent:
                self.mark_actions_sent([action.id for action in actions])
            self._refresh_counts(device.device_id)
            return actions

    def mark_actions_sent(self, action_ids: list[str]) -> None:
        with self._lock:
            ids = set(action_ids)
            for action in self._iter_actions():
                if action.id in ids and action.status == ActionStatus.queued:
                    action.status = ActionStatus.sent
                    action.sent_at = now_utc()
            for device_id in list(self._devices):
                self._refresh_counts(device_id)

    def ack(self, *, device_id: str | None, action_id: str | None, ok: bool | None, line: str | None, error: str | None) -> tuple[ActionRecord, DeviceSnapshot, bool]:
        if line:
            action_id, parsed_ok = parse_ack_line(line)
            ok = parsed_ok if ok is None else ok
        if not action_id:
            raise ValueError("action_id or ACK line is required")
        if ok is None:
            ok = True

        with self._lock:
            action = self._find_action(action_id, device_id)
            if action is None:
                raise KeyError(action_id)
            action.status = ActionStatus.acked if ok else ActionStatus.failed
            action.acked_at = now_utc()
            action.error = None if ok else (error or "STM32 returned ERR")
            device = self.ensure_device(action.device_id)
            device.last_ack = {
                "action_id": action.id,
                "ok": ok,
                "line": line,
                "error": action.error,
                "time": action.acked_at.isoformat(),
            }
            if ok:
                device.ack_ok_count += 1
            else:
                device.ack_err_count += 1
                device.state = DeviceRunState.error
            device.last_seen = now_utc()
            self._refresh_counts(device.device_id)
            return action, device, ok

    def diagnostics(self, device_id: str | None) -> tuple[DeviceSnapshot, list[ActionRecord], list[ActionRecord], list[ActionRecord]]:
        with self._lock:
            device = self.ensure_device(device_id)
            actions = self._actions[device.device_id]
            queued = [action for action in actions if action.status == ActionStatus.queued]
            sent = [action for action in actions if action.status == ActionStatus.sent]
            recent = actions[-20:]
            self._refresh_counts(device.device_id)
            return device, queued, sent, recent

    def _find_action(self, action_id: str, device_id: str | None) -> ActionRecord | None:
        if device_id and device_id in self._actions:
            for action in self._actions[device_id]:
                if action.id == action_id:
                    return action
        for action in self._iter_actions():
            if action.id == action_id:
                return action
        return None

    def _iter_actions(self) -> list[ActionRecord]:
        return [action for actions in self._actions.values() for action in actions]

    def _refresh_counts(self, device_id: str) -> None:
        device = self._devices[device_id]
        device.pending_action_count = sum(
            1 for action in self._actions.get(device_id, []) if action.status in {ActionStatus.queued, ActionStatus.sent}
        )

    def _append_dialogue_turn(self, device: DeviceSnapshot, role: str, text: str, source: str | None) -> None:
        message = text.strip()
        if not message:
            return
        device.recent_dialogue.append(
            DialogueTurn(
                role=role,
                text=message,
                time=now_utc(),
                source=source,
            )
        )
        if len(device.recent_dialogue) > 12:
            device.recent_dialogue = device.recent_dialogue[-12:]

    def _load_rfid_users(self) -> None:
        if not self._rfid_registry_path or not self._rfid_registry_path.exists():
            return
        try:
            payload = json.loads(self._rfid_registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, list):
            return

        loaded: dict[str, RfidUser] = {}
        for item in payload:
            try:
                user = RfidUser.model_validate(item)
            except Exception:
                continue
            loaded[user.uid] = user
        self._rfid_users = loaded

    def _save_rfid_users(self) -> None:
        if not self._rfid_registry_path:
            return
        self._rfid_registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [user.model_dump(mode="json") for user in sorted(self._rfid_users.values(), key=lambda item: item.uid)]
        temp_path = self._rfid_registry_path.with_suffix(f"{self._rfid_registry_path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self._rfid_registry_path)
