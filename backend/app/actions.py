from __future__ import annotations

import re
import unicodedata
from typing import Any

from .schemas import ActionSpec


def compact_text(value: Any, max_len: int = 80) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    while "  " in text:
        text = text.replace("  ", " ")
    return text[:max_len] if text else "OK"


def protocol_token(value: Any, max_len: int = 24) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    while "  " in text:
        text = text.replace("  ", " ")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")
    return (text[:max_len] if text else "-") or "-"


def fan_level(payload: dict[str, Any]) -> int:
    if "level" in payload:
        return max(1, min(3, int(payload["level"])))
    speed = int(payload.get("speed", 70))
    if speed <= 33:
        return 1
    if speed <= 66:
        return 2
    return 3


def servo_angle(payload: dict[str, Any]) -> int:
    value = payload.get("angle", payload.get("action", 90))
    if isinstance(value, str):
        action = value.strip().upper()
        presets = {
            "CLOSE": 0,
            "CLOSED": 0,
            "LOCK": 0,
            "OFF": 0,
            "OPEN": 90,
            "ON": 90,
            "UNLOCK": 90,
            "MID": 90,
            "MIDDLE": 90,
            "MAX": 180,
        }
        if action in presets:
            return presets[action]
        value = action
    return max(0, min(180, int(value)))


def volume_level(payload: dict[str, Any]) -> str:
    value = payload.get("level", payload.get("volume", 10))
    if isinstance(value, str) and value.strip().lower() in {"up", "down"}:
        return value.strip().upper()
    return str(max(0, min(16, int(value))))


def music_preset(payload: dict[str, Any]) -> str:
    value = compact_text(payload.get("preset", payload.get("song", payload.get("tune", "success"))), 16)
    preset = value.strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "OK": "SUCCESS",
        "DONE": "SUCCESS",
        "WIN": "SUCCESS",
        "VICTORY": "SUCCESS",
        "WARN": "ALERT",
        "WARNING": "ALERT",
        "BOOT": "STARTUP",
        "START": "STARTUP",
        "HAPPY": "BIRTHDAY",
        "STOP_MUSIC": "STOP",
        "OFF": "STOP",
    }
    preset = aliases.get(preset, preset)
    allowed = {"SUCCESS", "ALERT", "SCALE", "STARTUP", "BIRTHDAY", "STOP"}
    return preset if preset in allowed else "SUCCESS"


def ui_state(payload: dict[str, Any]) -> str:
    value = compact_text(payload.get("state", payload.get("status", "IDLE")), 12).upper()
    aliases = {
        "BLUE": "LISTEN",
        "LISTENING": "LISTEN",
        "RECORDING": "LISTEN",
        "GREEN": "OUTPUT",
        "OUTPUT": "OUTPUT",
        "SPEAKING": "OUTPUT",
        "DONE": "ACK",
        "OK": "ACK",
    }
    state = aliases.get(value, value)
    allowed = {"LISTEN", "THINK", "ACTION", "ACK", "IDLE", "ERROR", "OUTPUT"}
    return state if state in allowed else "IDLE"


def compact_utf8_text(value: Any, max_bytes: int = 180) -> str:
    text = compact_text(value, max_bytes)
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    truncated = encoded[:max_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return "OK"


TTS_TRANSLATION = str.maketrans(
    {
        "“": "",
        "”": "",
        "‘": "",
        "’": "",
        "\"": "",
        "'": "",
        "～": "。",
        "~": "。",
        "…": "。",
        "—": "-",
        "–": "-",
    }
)


SYN6288_NATURAL_PREFIX = ""
SYN6288_SENTENCE_ENDINGS = "。！？.!?"
SYN6288_PAUSES = "，,、；;：:"
SYN6288_OPENING_PHRASES = ("没问题", "好的", "收到", "可以", "我在")


def syn6288_naturalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return f"{SYN6288_NATURAL_PREFIX}OK."

    for phrase in SYN6288_OPENING_PHRASES:
        if text.startswith(phrase) and len(text) > len(phrase):
            next_char = text[len(phrase)]
            if next_char not in SYN6288_PAUSES + SYN6288_SENTENCE_ENDINGS and not next_char.isspace():
                text = f"{phrase}，{text[len(phrase):]}"
            break

    if text[-1] not in SYN6288_SENTENCE_ENDINGS:
        text = f"{text}。"

    return f"{SYN6288_NATURAL_PREFIX}{text}"


def safe_tts_text(value: Any, max_bytes: int = 30) -> str:
    text = compact_text(value, max_bytes * 2).translate(TTS_TRANSLATION)
    cleaned: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category in {"Cc", "Cf", "Cs"}:
            continue
        if ord(char) > 0xFFFF:
            continue
        cleaned.append(char)
    return compact_utf8_text(syn6288_naturalize("".join(cleaned).strip()), max_bytes)


def utf8_hex(value: Any, max_bytes: int = 180) -> str:
    text = compact_utf8_text(value, max_bytes)
    return text.encode("utf-8").hex().upper()


def command_from_action(action: ActionSpec) -> str:
    payload = action.payload
    action_type = action.type

    if action_type == "tts_speak":
        return f"NET:TTSHEX:{safe_tts_text(payload.get('text')).encode('utf-8').hex().upper()}"
    if action_type == "audio_stop":
        return "NET:TTS:STOP"
    if action_type == "volume_control":
        return f"NET:VOLUME:{volume_level(payload)}"
    if action_type == "oled_display":
        return f"NET:OLED:{compact_text(payload.get('text'), 40)}"
    if action_type == "user_context":
        user_id = protocol_token(payload.get("user_id"), 24)
        uid = protocol_token(payload.get("uid") or payload.get("card_uid"), 16)
        mode = protocol_token(payload.get("mode"), 12).upper()
        return f"NET:UI:USER:{user_id}:{uid}:{mode}"
    if action_type == "fan_control":
        state = str(payload.get("state", "on")).lower()
        if state in {"off", "0", "false"}:
            return "NET:FAN:OFF"
        return f"NET:FAN:ON:{fan_level(payload)}"
    if action_type == "buzzer_alert":
        return "NET:BEEP"
    if action_type == "buzzer_music":
        return f"NET:MUSIC:{music_preset(payload)}"
    if action_type == "ui_state":
        return f"NET:UI:{ui_state(payload)}"
    if action_type == "focus_mode":
        minutes = max(1, min(180, int(payload.get("minutes", 25))))
        return f"NET:OLED:FOCUS {minutes} MIN"
    if action_type == "servo_action":
        return f"NET:SERVO:{servo_angle(payload)}"
    if action_type == "lock_control":
        state = str(payload.get("state", "on")).upper()
        return f"NET:LOCK:{'OFF' if state in {'OFF', '0', 'FALSE', 'UNLOCK'} else 'ON'}"
    if action_type == "lamp_control":
        state = compact_text(payload.get("state", "IDLE"), 8).upper()
        if state not in {"IDLE", "BUSY", "OFF"}:
            state = "IDLE"
        return f"NET:AI:{state}"

    raise ValueError(f"unsupported action type: {action_type}")


def wrap_command(action_id: str, command: str) -> str:
    return f"NET:CMD:{action_id}:{command}"


def parse_ack_line(line: str) -> tuple[str, bool]:
    parts = line.strip().split(":")
    if len(parts) < 4 or parts[0] != "BT" or parts[1] != "ACK":
        raise ValueError("ACK line must look like BT:ACK:<action_id>:OK/ERR")
    return parts[2], parts[3].upper() == "OK"
