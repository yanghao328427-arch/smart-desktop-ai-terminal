from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from .actions import command_from_action, parse_ack_line, wrap_command
from .context_db import ContextDatabase, EnrollmentRecord
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


DEVICE_ONLINE_TTL_SECONDS = 30


@dataclass
class RfidScanResult:
    uid: str
    user: RfidUser | None
    state: DeviceSnapshot
    enrolled: bool = False
    enroll_id: str | None = None


class RuntimeStore:
    def __init__(
        self,
        default_device_id: str,
        default_edge_id: str,
        *,
        rfid_registry_path: str | Path | None = None,
        context_db_path: str | Path | None = None,
    ) -> None:
        self.default_device_id = default_device_id
        self.default_edge_id = default_edge_id
        self._devices: dict[str, DeviceSnapshot] = {}
        self._actions: dict[str, list[ActionRecord]] = {}
        self._rfid_registry_path = Path(rfid_registry_path) if rfid_registry_path else None
        self.context_db = ContextDatabase(context_db_path or Path(__file__).resolve().parents[1] / "data" / "context.sqlite3")
        self._lock = RLock()
        self.context_db.migrate_rfid_json(self._rfid_registry_path)
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
            stamp = now_utc()
            device.session_connected = connected
            device.online = connected
            device.state = DeviceRunState.idle if connected else DeviceRunState.offline
            device.last_seen = stamp
            if connected:
                self._mark_device_seen(device, stamp)
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
            stamp = now_utc()
            device.online = online
            device.uart_ok = uart_ok
            device.voice_state = voice_state
            device.last_seen = stamp
            device.device_last_seen = stamp
            device.device_age_seconds = 0.0
            device.sensors["uptime_ms"] = uptime_ms
            if online and device.state == DeviceRunState.offline:
                device.state = DeviceRunState.idle
            if not online:
                device.session_connected = False
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
            stamp = now_utc()
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
            device.last_seen = stamp
            self._mark_device_seen(device, stamp)
            if device.state == DeviceRunState.offline:
                device.state = DeviceRunState.idle
            self._refresh_counts(device.device_id)
            return device

    def list_users(self) -> list[RfidUser]:
        return self.context_db.list_users()

    def create_user(
        self,
        name: str,
        mode: UserMode,
        profile_summary: str | None = None,
        admin_notes: str | None = None,
    ) -> RfidUser:
        return self.context_db.create_user(
            name=name,
            mode=mode,
            profile_summary=profile_summary,
            admin_notes=admin_notes,
        )

    def select_user_context(self, device_id: str | None, user_id: str, source: str = "control") -> tuple[RfidUser, DeviceSnapshot]:
        with self._lock:
            user = self.context_db.get_user(user_id)
            if user is None:
                raise KeyError(user_id)
            device = self.ensure_device(device_id)
            session_id = self.context_db.create_session(user_id=user.user_id, device_id=device.device_id, source=source)
            self._apply_user_context(device, user, session_id, source=source, physical_card=False)
            self._refresh_counts(device.device_id)
            return user, device

    def start_rfid_enrollment(
        self,
        *,
        device_id: str | None,
        user_id: str | None,
        name: str | None,
        mode: UserMode,
        profile_summary: str | None,
        admin_notes: str | None,
        ttl_seconds: int,
    ) -> EnrollmentRecord:
        device = self.ensure_device(device_id)
        return self.context_db.start_enrollment(
            device_id=device.device_id,
            user_id=user_id,
            name=name,
            mode=mode,
            profile_summary=profile_summary,
            admin_notes=admin_notes,
            ttl_seconds=ttl_seconds,
        )

    def rfid_enrollment_status(self, enroll_id: str) -> EnrollmentRecord | None:
        return self.context_db.get_enrollment(enroll_id)

    def cancel_rfid_enrollment(self, enroll_id: str) -> EnrollmentRecord | None:
        return self.context_db.cancel_enrollment(enroll_id)

    def register_rfid(
        self,
        uid: str,
        name: str,
        mode: UserMode,
        device_id: str | None,
        profile_summary: str | None = None,
        admin_notes: str | None = None,
    ) -> tuple[RfidUser, DeviceSnapshot]:
        normalized_uid = normalize_uid(uid)
        if not normalized_uid:
            raise ValueError("RFID UID cannot be empty")
        with self._lock:
            user = self.context_db.create_user_with_card(
                uid=normalized_uid,
                name=name.strip() or normalized_uid,
                mode=mode,
                profile_summary=profile_summary,
                admin_notes=admin_notes,
                source="manual",
            )
            device = self.ensure_device(device_id)
            session_id = self.context_db.create_session(user_id=user.user_id, device_id=device.device_id, source="manual_register")
            self._apply_user_context(device, user, session_id, source="manual_register", physical_card=False)
            if device.state == DeviceRunState.offline:
                device.state = DeviceRunState.idle
            device.last_seen = now_utc()
            self._refresh_counts(device.device_id)
            return user, device

    def scan_rfid(self, uid: str, device_id: str | None, source: str = "rc522") -> RfidScanResult:
        normalized_uid = normalize_uid(uid)
        if not normalized_uid:
            raise ValueError("RFID UID cannot be empty")
        with self._lock:
            device = self.ensure_device(device_id)
            stamp = now_utc()
            source_value = (source or "rc522").strip()[:40] or "rc522"
            user = self.context_db.get_card_user(normalized_uid)
            enrolled = False
            enroll_id = None
            if user is None:
                enrollment = self.context_db.pending_enrollment_for_device(device.device_id)
                if enrollment:
                    completed = self.context_db.complete_enrollment(enrollment.enroll_id, normalized_uid)
                    user = self.context_db.get_card_user(normalized_uid)
                    enrolled = user is not None
                    enroll_id = completed.enroll_id
            device.online = True
            device.last_seen = stamp
            self._mark_device_seen(device, stamp)
            device.sensors["last_rfid_uid"] = normalized_uid
            device.sensors["last_rfid_authorized"] = bool(user)
            device.sensors["last_rfid_at"] = stamp.isoformat()
            device.sensors["last_rfid_source"] = source_value
            device.sensors["last_rfid_enrolled"] = enrolled
            if enroll_id:
                device.sensors["last_rfid_enroll_id"] = enroll_id
            if device.state == DeviceRunState.offline:
                device.state = DeviceRunState.idle
            if user:
                session_source = "rfid_enroll" if enrolled else source_value
                session_id = self.context_db.create_session(user_id=user.user_id, device_id=device.device_id, source=session_source)
                self._apply_user_context(
                    device,
                    user,
                    session_id,
                    source=session_source,
                    physical_card=source_value == "rc522",
                )
            else:
                self._clear_user_context(device)
                self.context_db.audit(
                    "rfid_unknown_denied",
                    actor=source_value,
                    device_id=device.device_id,
                    uid=normalized_uid,
                )
            self._refresh_counts(device.device_id)
            return RfidScanResult(uid=normalized_uid, user=user, state=device, enrolled=enrolled, enroll_id=enroll_id)

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
            if device.current_user and device.active_session_id:
                self.context_db.add_memory_event(
                    user_id=device.current_user.user_id,
                    session_id=device.active_session_id,
                    role="user",
                    text=text,
                    source=source,
                )
                self.context_db.add_memory_event(
                    user_id=device.current_user.user_id,
                    session_id=device.active_session_id,
                    role="assistant",
                    text=reply,
                    source=source,
                )
                device.recent_dialogue = self.context_db.recent_dialogue(
                    user_id=device.current_user.user_id,
                    session_id=None,
                )
            else:
                device.recent_dialogue = []
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
        hardware_seen: bool = False,
    ) -> DeviceSnapshot:
        with self._lock:
            device = self.ensure_device(device_id)
            stamp = now_utc()
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
            device.sensors["last_asr_at"] = stamp.isoformat()
            device.last_seen = stamp
            if hardware_seen:
                self._mark_device_seen(device, stamp)
            self._refresh_counts(device.device_id)
            return device

    def note_button_event(self, device_id: str | None, line: str, source: str = "stm32") -> DeviceSnapshot:
        with self._lock:
            device = self.ensure_device(device_id)
            stamp = now_utc()
            clean_line = (line or "").strip()[:120]
            event = clean_line.removeprefix("BT:BTN:") if clean_line.startswith("BT:BTN:") else clean_line
            parts = [part for part in event.split(":") if part]
            duration_ms = None
            if parts and parts[-1].isdigit():
                duration_ms = int(parts[-1])

            seq = int(device.sensors.get("last_button_seq") or 0) + 1
            device.sensors["last_button_seq"] = seq
            device.sensors["last_button_line"] = clean_line
            device.sensors["last_button_event"] = event
            device.sensors["last_button_source"] = (source or "stm32")[:40]
            device.sensors["last_button_at"] = stamp.isoformat()
            if duration_ms is not None:
                device.sensors["last_button_duration_ms"] = duration_ms

            if event.startswith("KEY2:HOLD_START"):
                device.state = DeviceRunState.recording
                device.voice_state = "ptt_recording"
            elif event.startswith("KEY2:UP"):
                device.state = DeviceRunState.listen
                device.voice_state = "ptt_uploading"
            elif event.startswith("KEY2:SHORT") or event.startswith("KEY2:DOWN"):
                device.state = DeviceRunState.listen
                device.voice_state = "interrupted"
            device.last_seen = stamp
            self._refresh_counts(device.device_id)
            return device

    def interrupt_seq(self, device_id: str | None) -> int:
        with self._lock:
            device = self.ensure_device(device_id)
            return int(device.sensors.get("interrupt_seq") or 0)

    def interrupt_output(self, device_id: str | None, reason: str = "button") -> DeviceSnapshot:
        with self._lock:
            device = self.ensure_device(device_id)
            stamp = now_utc()
            device.sensors["interrupt_seq"] = int(device.sensors.get("interrupt_seq") or 0) + 1
            device.sensors["last_interrupt_reason"] = reason[:40]
            device.sensors["last_interrupt_at"] = stamp.isoformat()
            device.voice_state = "interrupted"
            device.state = DeviceRunState.listen
            for action in self._actions.get(device.device_id, []):
                if action.status == ActionStatus.queued and action.type == "tts_speak":
                    action.status = ActionStatus.failed
                    action.acked_at = stamp
                    action.error = "interrupted before send"
            self._refresh_counts(device.device_id)
            return device

    def enqueue_actions(
        self,
        device_id: str | None,
        specs: list[ActionSpec],
        *,
        control_source: str = "system",
        control_priority: int = 0,
    ) -> list[ActionRecord]:
        with self._lock:
            device = self.ensure_device(device_id)
            records: list[ActionRecord] = []
            for spec in uart_safe_action_order(specs):
                if not self._accept_control_action(device, spec, control_source, control_priority):
                    continue
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
            self._mark_device_seen(device)
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
            self._mark_device_seen(device, action.acked_at)
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
            device.last_seen = action.acked_at
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

    def _accept_control_action(
        self,
        device: DeviceSnapshot,
        spec: ActionSpec,
        control_source: str,
        control_priority: int,
    ) -> bool:
        if spec.type != "lock_control":
            return True

        requested_state = str(spec.payload.get("state", "")).strip().lower()
        if requested_state not in {"on", "off"}:
            return True

        sensors = device.sensors
        source = (control_source or "system").strip()[:40] or "system"
        try:
            current_priority = int(sensors.get("lock_control_priority", -1))
        except (TypeError, ValueError):
            current_priority = -1
        current_state = sensors.get("lock_state")

        if control_priority < current_priority and current_state and requested_state != current_state:
            sensors["lock_control_skipped_source"] = source
            sensors["lock_control_skipped_priority"] = control_priority
            sensors["lock_control_skipped_state"] = requested_state
            sensors["lock_control_skip_reason"] = f"lower than {sensors.get('lock_control_source', 'unknown')}"
            sensors["lock_control_skipped_at"] = now_utc().isoformat()
            return False

        sensors["lock_state"] = requested_state
        sensors["lock_control_source"] = source
        sensors["lock_control_priority"] = control_priority
        sensors["lock_control_at"] = now_utc().isoformat()
        return True

    def _apply_user_context(
        self,
        device: DeviceSnapshot,
        user: RfidUser,
        session_id: str,
        *,
        source: str,
        physical_card: bool,
    ) -> None:
        device.current_user = user
        device.active_session_id = session_id
        device.mode = user.mode
        device.recent_dialogue = self.context_db.recent_dialogue(user_id=user.user_id, session_id=None)
        device.sensors["active_user_id"] = user.user_id
        device.sensors["active_session_id"] = session_id
        device.sensors["active_context_source"] = source
        device.sensors["active_context_physical_card"] = physical_card
        if user.uid:
            device.sensors["active_rfid_uid"] = user.uid

    def _clear_user_context(self, device: DeviceSnapshot) -> None:
        device.current_user = None
        device.active_session_id = None
        device.mode = None
        device.recent_dialogue = []
        device.sensors.pop("active_user_id", None)
        device.sensors.pop("active_session_id", None)
        device.sensors.pop("active_context_source", None)
        device.sensors.pop("active_context_physical_card", None)
        device.sensors.pop("active_rfid_uid", None)

    def _refresh_counts(self, device_id: str) -> None:
        device = self._devices[device_id]
        device.pending_action_count = sum(
            1 for action in self._actions.get(device_id, []) if action.status in {ActionStatus.queued, ActionStatus.sent}
        )
        self._apply_device_freshness(device)

    def _mark_device_seen(self, device: DeviceSnapshot, stamp: datetime | None = None) -> None:
        actual_stamp = stamp or now_utc()
        device.device_last_seen = actual_stamp
        device.device_age_seconds = 0.0
        device.online = True
        device.last_seen = actual_stamp

    def _apply_device_freshness(self, device: DeviceSnapshot, stamp: datetime | None = None) -> None:
        if device.device_last_seen is None:
            device.device_age_seconds = None
            if device.online:
                device.online = False
                device.session_connected = False
                device.uart_ok = False
            return

        actual_stamp = stamp or now_utc()
        age_seconds = max(0.0, (actual_stamp - device.device_last_seen).total_seconds())
        device.device_age_seconds = round(age_seconds, 3)
        if age_seconds > DEVICE_ONLINE_TTL_SECONDS:
            device.online = False
            device.session_connected = False
            device.uart_ok = False

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
