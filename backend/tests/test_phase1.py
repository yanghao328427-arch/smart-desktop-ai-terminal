import asyncio
import tempfile
import wave
from datetime import timedelta
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from app.ai import (
    DashScopeOpenAIClient,
    build_system_prompt,
    format_news_context,
    is_news_query,
    parse_cloud_reply,
    parse_rss_items,
    speech_text,
)
from app.asr import TranscriptionResult
from app.actions import command_from_action
from app.config import Settings
from app.main import create_app, rfid_access_speech, rfid_spoken_name
from app.schemas import ActionSpec
from app.store import DEVICE_ONLINE_TTL_SECONDS, now_utc


def make_client(**settings_overrides) -> TestClient:
    data_dir = Path(tempfile.mkdtemp())
    settings_overrides.setdefault("rfid_registry_path", data_dir / "rfid_users.json")
    settings_overrides.setdefault("context_db_path", data_dir / "context.sqlite3")
    settings_overrides.setdefault("ai_provider", "mock")
    settings_overrides.setdefault("dashscope_api_key", None)
    settings_overrides.setdefault("control_token", None)
    app = create_app(Settings(**settings_overrides))
    return TestClient(app)


def register_card(
    client: TestClient,
    uid: str = "04A1B2C3",
    name: str = "student",
    mode: str = "study",
    token: str | None = None,
    **extra: str,
):
    headers = {"X-Demo-Token": token} if token else {}
    payload = {"device_id": "desktop-agent-001", "uid": uid, "name": name, "mode": mode, **extra}
    return client.post("/api/rfid/register", headers=headers, json=payload)


def make_wav_bytes(sample_rate: int = 16000, channels: int = 1, frames: int = 1600) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frames * channels)
    return buffer.getvalue()


class StubAsrClient:
    def __init__(self, result: TranscriptionResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def transcribe(self, audio: bytes, **kwargs) -> TranscriptionResult:
        self.calls.append({"audio_bytes": len(audio), **kwargs})
        return self.result


class FailIfCalledAsrClient:
    async def transcribe(self, audio: bytes, **kwargs) -> TranscriptionResult:
        raise AssertionError("ASR client should not be called when mock_text is provided")


def test_health_and_default_state():
    client = make_client()

    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["protocol"] == "smart-desktop-realtime-v1"
    assert health["ai_provider"] == "mock"
    assert health["ai_model"] == "local-rules"
    assert health["cloud_ready"] is False

    state = client.get("/api/state/desktop-agent-001").json()
    assert state["device_id"] == "desktop-agent-001"
    assert state["state"] == "offline"
    assert state["pending_action_count"] == 0


def test_control_token_protects_public_mutations():
    client = make_client(control_token="secret-token")

    blocked = client.post("/api/chat", json={"text": "你是谁"})
    wrong = client.post("/api/chat", headers={"X-Demo-Token": "wrong"}, json={"text": "你是谁"})
    allowed = client.post("/api/chat", headers={"X-Demo-Token": "secret-token"}, json={"text": "你是谁"})
    rfid_blocked = client.post("/api/rfid/scan", json={"uid": "04A1B2C3"})
    rfid_allowed = client.post(
        "/api/rfid/scan",
        headers={"X-Demo-Token": "secret-token"},
        json={"uid": "04A1B2C3", "source": "web_simulator"},
    )

    assert blocked.status_code == 403
    assert wrong.status_code == 401
    assert allowed.status_code == 200
    assert rfid_blocked.status_code == 401
    assert rfid_allowed.status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/state/desktop-agent-001").status_code == 200
    action = client.post("/api/hardware/action", json={"type": "ui_state", "payload": {"state": "listen"}})
    assert action.status_code == 403


def test_device_token_allows_real_rfid_scan_but_not_registration():
    client = make_client(control_token="control-secret", device_token="device-secret")

    device_register = client.post(
        "/api/rfid/register",
        headers={"X-Device-Token": "device-secret"},
        json={"uid": "43 6A 4B 07", "name": "student", "mode": "study"},
    )
    control_register = register_card(
        client,
        uid="43 6A 4B 07",
        name="student",
        mode="study",
        token="control-secret",
        profile_summary="喜欢先看结论再看依据。",
    )
    device_scan = client.post(
        "/api/rfid/scan",
        headers={"X-Device-Token": "device-secret"},
        json={"uid": "436A4B07", "source": "rc522"},
    )

    assert device_register.status_code == 401
    assert control_register.status_code == 200
    assert device_scan.status_code == 200
    data = device_scan.json()
    assert data["source"] == "rc522"
    assert data["authorized"] is True
    assert data["user"]["profile_summary"] == "喜欢先看结论再看依据。"
    assert data["state"]["active_session_id"]
    assert data["state"]["sensors"]["last_rfid_source"] == "rc522"


def test_health_reports_dashscope_cloud_ready_without_exposing_key():
    client = make_client(ai_provider="dashscope_openai", dashscope_api_key="test-key", ai_model="qwen-plus")

    health = client.get("/api/health").json()

    assert health["ai_provider"] == "dashscope_openai"
    assert health["ai_model"] == "qwen-plus"
    assert health["cloud_ready"] is True
    assert "key" not in str(health).lower()


def test_tts_hex_command_limits_utf8_payload_bytes():
    command = command_from_action(ActionSpec(type="tts_speak", payload={"text": "智能对话" * 80}))
    hex_payload = command.removeprefix("NET:TTSHEX:")

    assert len(bytes.fromhex(hex_payload)) <= 120


def test_cloud_reply_parser_prefers_structured_speech():
    reply, speech = parse_cloud_reply(
        '```json\n{"reply":"这是完整回复，会展示在网页上。","speech":"这是短播报。"}\n```'
    )

    assert reply == "这是完整回复，会展示在网页上。"
    assert speech == "这是短播报。"


def test_speech_text_keeps_broadcast_sentence_short():
    speech = speech_text("当前设备在线。实时会话已连接。串口链路正常。温度 26.5 度，湿度 48.2%。距离数据暂时不可用。")

    assert speech.startswith("当前设备在线")
    assert len(speech.encode("utf-8")) <= 90


def test_news_query_detection_and_rss_context_formatting():
    xml = """<?xml version="1.0" encoding="UTF-8" ?>
    <rss><channel>
      <item>
        <title>Global leaders meet for climate talks</title>
        <link>https://example.com/climate</link>
        <description>Countries discuss new climate funding.</description>
        <pubDate>Thu, 11 Jun 2026 08:00:00 GMT</pubDate>
      </item>
    </channel></rss>
    """

    items = parse_rss_items(xml, "Example News")
    context = format_news_context(items)

    assert is_news_query("今天的世界新闻有哪些")
    assert items[0].title == "Global leaders meet for climate talks"
    assert "公开 RSS 新闻源" in context
    assert "Global leaders meet for climate talks" in context


def test_system_prompt_allows_complex_model_answers():
    client = make_client()
    state = client.get("/api/state/desktop-agent-001").json()
    prompt = build_system_prompt(client.app.state.store.ensure_device(state["device_id"]))

    assert "通用智能助手" in prompt
    assert "复杂问题" in prompt
    assert "不要为了播报而压缩" in prompt


def test_system_prompt_includes_rfid_user_context():
    client = make_client()
    register_card(
        client,
        profile_summary="这个用户常做答辩准备，偏好先给可执行结论。",
        admin_notes="遇到硬件状态问题时先区分真实在线和网页输入。",
    )

    prompt = build_system_prompt(client.app.state.store.ensure_device("desktop-agent-001"))

    assert "上下文摘要" in prompt
    assert "答辩准备" in prompt
    assert "真实在线" in prompt


def test_rfid_register_updates_user_mode():
    client = make_client()

    response = register_card(client, uid="04 a1 b2 c3", profile_summary="偏好简短、直接的上下文延续。")

    assert response.status_code == 200
    data = response.json()
    assert data["user"]["uid"] == "04A1B2C3"
    assert data["state"]["current_user"]["name"] == "student"
    assert data["state"]["current_user"]["profile_summary"] == "偏好简短、直接的上下文延续。"
    assert data["state"]["active_session_id"]
    assert data["state"]["mode"] == "study"
    assert data["state"]["state"] == "idle"


def test_rfid_scan_unlocks_registered_card_and_rejects_unknown_card():
    client = make_client()

    register_card(client, uid="04:A1:B2:C3")

    accepted = client.post(
        "/api/rfid/scan",
        json={"device_id": "desktop-agent-001", "uid": "04 a1 b2 c3", "source": "web_simulator"},
    ).json()
    assert accepted["authorized"] is True
    assert accepted["source"] == "web_simulator"
    assert accepted["user"]["name"] == "student"
    assert accepted["state"]["mode"] == "study"
    assert accepted["state"]["sensors"]["last_rfid_source"] == "web_simulator"
    assert any(":NET:LOCK:OFF" in line for line in accepted["commands"])
    assert any(":NET:OLED:STUDY MODE" in line for line in accepted["commands"])
    assert any(":NET:TTSHEX:" in line for line in accepted["commands"])
    tts_command = next(line.split(":NET:TTSHEX:", 1)[1] for line in accepted["commands"] if ":NET:TTSHEX:" in line)
    assert bytes.fromhex(tts_command).decode("utf-8") == "学生，解锁成功。"

    rejected = client.post(
        "/api/rfid/scan",
        json={"device_id": "desktop-agent-001", "uid": "DE AD BE EF", "source": "web_simulator"},
    ).json()
    assert rejected["authorized"] is False
    assert rejected["user"] is None
    assert rejected["state"]["sensors"]["last_rfid_authorized"] is False
    assert rejected["state"]["sensors"]["last_rfid_at"]
    assert rejected["state"]["current_user"] is None
    assert rejected["state"]["mode"] is None
    assert any(":NET:LOCK:ON" in line for line in rejected["commands"])


def test_rfid_speech_uses_natural_names_without_spelling_internal_ids():
    assert rfid_spoken_name("student") == "学生"
    assert rfid_spoken_name("王老师") == "王老师"
    assert rfid_spoken_name("alice_01") == ""
    assert rfid_access_speech("student") == "学生，解锁成功。"
    assert rfid_access_speech("alice_01") == "解锁成功，欢迎回来。"
    assert rfid_access_speech("teacher", enrolled=True) == "老师，注册成功。"


def test_context_db_persists_registered_card_across_app_restart(tmp_path):
    db_path = tmp_path / "context.sqlite3"

    first_client = make_client(context_db_path=db_path)
    response = register_card(first_client, uid="43 6A 4B 07")

    assert response.status_code == 200
    assert db_path.exists() is True

    second_client = make_client(context_db_path=db_path)
    accepted = second_client.post("/api/rfid/scan", json={"device_id": "desktop-agent-001", "uid": "436A4B07"}).json()

    assert accepted["authorized"] is True
    assert accepted["user"]["name"] == "student"
    assert accepted["state"]["mode"] == "study"


def test_online_rfid_enrollment_binds_next_real_scan():
    client = make_client(control_token="control-secret", device_token="device-secret")

    started = client.post(
        "/api/rfid/enroll/start",
        headers={"X-Demo-Token": "control-secret"},
        json={
            "device_id": "desktop-agent-001",
            "name": "student",
            "mode": "study",
            "profile_summary": "这张卡对应学生自己的连续上下文。",
        },
    )

    assert started.status_code == 200
    enroll_id = started.json()["enroll_id"]
    scanned = client.post(
        "/api/rfid/scan",
        headers={"X-Device-Token": "device-secret"},
        json={"device_id": "desktop-agent-001", "uid": "43 6A 4B 07", "source": "rc522"},
    ).json()
    status = client.get(f"/api/rfid/enroll/{enroll_id}", headers={"X-Demo-Token": "control-secret"}).json()

    assert scanned["authorized"] is True
    assert scanned["enrolled"] is True
    assert scanned["enroll_id"] == enroll_id
    assert scanned["user"]["name"] == "student"
    assert scanned["user"]["uid"] == "436A4B07"
    assert scanned["state"]["active_session_id"]
    assert status["status"] == "completed"
    assert status["uid"] == "436A4B07"


def test_unknown_card_cannot_chat_until_card_or_control_context_exists():
    client = make_client(control_token="control-secret", device_token="device-secret")

    denied = client.post("/api/chat", json={"text": "你是谁"})
    with_control = client.post(
        "/api/chat",
        headers={"X-Demo-Token": "control-secret"},
        json={"text": "你是谁"},
    )
    register_card(client, token="control-secret")
    still_denied_after_manual_register = client.post("/api/chat", json={"text": "你是谁"})
    client.post(
        "/api/rfid/scan",
        headers={"X-Device-Token": "device-secret"},
        json={"device_id": "desktop-agent-001", "uid": "04A1B2C3", "source": "rc522"},
    )
    after_card = client.post("/api/chat", json={"text": "你是谁"})

    assert denied.status_code == 403
    assert with_control.status_code == 200
    assert still_denied_after_manual_register.status_code == 403
    assert after_card.status_code == 200


def test_different_cards_route_to_different_user_contexts():
    client = make_client()

    register_card(client, uid="11 11 11 11", name="alice")
    client.post("/api/chat", json={"text": "我的代号是甲。"})
    register_card(client, uid="22 22 22 22", name="bob")
    client.post("/api/chat", json={"text": "我的代号是乙。"})

    client.post("/api/rfid/scan", json={"device_id": "desktop-agent-001", "uid": "11111111", "source": "web_simulator"})
    alice_reply = client.post("/api/chat", json={"text": "你记得我刚才说了什么吗"}).json()["reply"]
    client.post("/api/rfid/scan", json={"device_id": "desktop-agent-001", "uid": "22222222", "source": "web_simulator"})
    bob_reply = client.post("/api/chat", json={"text": "你记得我刚才说了什么吗"}).json()["reply"]

    assert "甲" in alice_reply
    assert "乙" not in alice_reply
    assert "乙" in bob_reply
    assert "甲" not in bob_reply


def test_chat_queues_commands_and_ack_line():
    client = make_client()

    chat = client.post("/api/chat", json={"device_id": "desktop-agent-001", "text": "你是谁"}).json()

    assert "智能桌面 AI 终端" in chat["reply"]
    assert len(chat["actions"]) >= 2
    assert any(action["type"] == "tts_speak" for action in chat["actions"])
    assert any(action["type"] == "oled_display" for action in chat["actions"])
    assert chat["actions"][-1]["type"] == "tts_speak"
    assert all(line.startswith("NET:CMD:act_") for line in chat["commands"])

    queued = client.get("/api/hardware/commands/desktop-agent-001").json()
    assert queued["commands"] == chat["commands"]
    action_id = queued["actions"][0]["id"]

    ack = client.post("/api/hardware/ack", json={"line": f"BT:ACK:{action_id}:OK"}).json()
    assert ack["ok"] is True
    assert ack["action"]["status"] == "acked"
    assert ack["state"]["ack_ok_count"] == 1

    diagnostics = client.get("/api/realtime/diagnostics/desktop-agent-001").json()
    assert diagnostics["state"]["last_ack"]["action_id"] == action_id
    assert diagnostics["state"]["pending_action_count"] == len(chat["actions"]) - 1


def test_web_chat_does_not_mark_unseen_hardware_online():
    client = make_client()

    chat = client.post("/api/chat", json={"device_id": "desktop-agent-001", "text": "你是谁"}).json()
    state = client.get("/api/state/desktop-agent-001").json()

    assert chat["state"]["online"] is False
    assert state["online"] is False
    assert state["device_last_seen"] is None


def test_device_goes_offline_when_hardware_snapshot_is_stale():
    client = make_client()
    response = client.post(
        "/api/hardware/heartbeat",
        json={
            "device_id": "desktop-agent-001",
            "edge_id": "esp32s3-sense-001",
            "online": True,
            "uart_ok": True,
            "voice_state": "idle",
            "uptime_ms": 1234,
        },
    ).json()
    assert response["online"] is True
    assert response["uart_ok"] is True
    assert response["device_last_seen"]

    device = client.app.state.store.ensure_device("desktop-agent-001")
    device.device_last_seen = now_utc() - timedelta(seconds=DEVICE_ONLINE_TTL_SECONDS + 1)

    state = client.get("/api/state/desktop-agent-001").json()
    diagnostics = client.get("/api/realtime/diagnostics/desktop-agent-001").json()

    assert state["online"] is False
    assert state["session_connected"] is False
    assert state["uart_ok"] is False
    assert state["device_age_seconds"] >= DEVICE_ONLINE_TTL_SECONDS
    assert diagnostics["state"]["online"] is False


def test_chat_maps_tool_commands():
    client = make_client()

    chat = client.post("/api/chat", json={"text": "打开风扇"}).json()

    assert "打开风扇" in chat["reply"]
    assert any(":NET:FAN:ON:2" in line for line in chat["commands"])
    assert any(action["type"] == "fan_control" for action in chat["actions"])


def test_chat_maps_absolute_and_relative_volume_commands():
    client = make_client()

    absolute = client.post("/api/chat", json={"text": "把音量调到8"}).json()
    louder = client.post("/api/chat", json={"text": "音量大一点"}).json()

    assert any(":NET:VOLUME:8" in line for line in absolute["commands"])
    assert absolute["actions"][-1]["type"] == "tts_speak"
    assert any(":NET:VOLUME:UP" in line for line in louder["commands"])


def test_cloud_client_uses_local_fast_path_for_hardware_actions():
    client = make_client()
    ai = DashScopeOpenAIClient(Settings(ai_provider="dashscope_openai", dashscope_api_key="test-key"))
    device = client.app.state.store.ensure_device("desktop-agent-001")

    plan = asyncio.run(ai.plan("打开风扇", device))

    assert any(action.type == "fan_control" for action in plan.actions)
    assert any(action.type == "tts_speak" for action in plan.actions)


def test_chat_can_answer_device_status_from_live_snapshot():
    client = make_client()
    client.post(
        "/api/hardware/telemetry",
        json={
            "device_id": "desktop-agent-001",
            "edge_id": "esp32s3-sense-001",
            "voice_state": "telemetry",
            "sensors": {
                "temperature_c": 26.5,
                "humidity_pct": 48.2,
                "pot_raw": 2048,
                "aht20_ok": True,
                "distance_ok": False,
            },
        },
    )

    response = client.post("/api/chat", json={"text": "现在状态怎么样"}).json()

    assert "当前设备在线" in response["reply"]
    assert "温度 26.5 度" in response["reply"]
    assert "湿度 48.2%" in response["reply"]
    assert response["speech"]
    assert response["state"]["last_speech"] == response["speech"]
    assert len(response["speech"].encode("utf-8")) <= 90
    assert any(":NET:OLED:STATUS OK" in line for line in response["commands"])


def test_chat_can_answer_temperature_question():
    client = make_client()
    client.post(
        "/api/hardware/telemetry",
        json={
            "device_id": "desktop-agent-001",
            "edge_id": "esp32s3-sense-001",
            "voice_state": "telemetry",
            "sensors": {
                "temperature_c": 25.3,
                "humidity_pct": 51.0,
                "aht20_ok": True,
            },
        },
    )

    response = client.post("/api/chat", json={"text": "现在温度多少"}).json()

    assert "当前温度约 25.3 度" in response["reply"]
    assert any(":NET:OLED:TEMP" in line for line in response["commands"])


def test_chat_can_remember_previous_user_turn():
    client = make_client()
    register_card(client)

    first = client.post("/api/chat", json={"text": "你是谁"}).json()
    second = client.post("/api/chat", json={"text": "你记得我刚才说了什么吗"}).json()

    assert first["reply"]
    assert "你是谁" in second["reply"]
    assert second["state"]["recent_dialogue"][-1]["role"] == "assistant"


def test_chat_can_give_advice_from_sensor_context():
    client = make_client()
    client.post(
        "/api/hardware/telemetry",
        json={
            "device_id": "desktop-agent-001",
            "edge_id": "esp32s3-sense-001",
            "voice_state": "telemetry",
            "sensors": {
                "temperature_c": 29.8,
                "humidity_pct": 58.4,
                "aht20_ok": True,
            },
        },
    )

    response = client.post("/api/chat", json={"text": "现在适合学习吗"}).json()

    assert "29.8 度" in response["reply"]
    assert "湿度 58.4%" in response["reply"]
    assert any(":NET:OLED:AI ADVICE" in line for line in response["commands"])


def test_chat_can_handle_combined_actions():
    client = make_client()

    response = client.post("/api/chat", json={"text": "打开风扇并进入专注30分钟"}).json()

    assert "打开风扇" in response["reply"]
    assert "30 分钟专注模式" in response["reply"]
    assert any(":NET:FAN:ON:2" in line for line in response["commands"])
    assert any(action["type"] == "focus_mode" and action["payload"]["minutes"] == 30 for action in response["actions"])


def test_chat_can_trigger_buzzer_music():
    client = make_client()

    response = client.post("/api/chat", json={"text": "\u64ad\u653e\u751f\u65e5\u6b4c"}).json()

    assert any(":NET:MUSIC:BIRTHDAY" in line for line in response["commands"])
    assert any(action["type"] == "buzzer_music" and action["payload"]["preset"] == "birthday" for action in response["actions"])


def test_hardware_telemetry_updates_sensor_snapshot():
    client = make_client()

    response = client.post(
        "/api/hardware/telemetry",
        json={
            "device_id": "desktop-agent-001",
            "edge_id": "esp32s3-sense-001",
            "voice_state": "telemetry",
            "sensors": {
                "temperature_c": 26.5,
                "humidity_pct": 48.2,
                "distance_cm": 31.4,
                "distance_zone": "near",
                "pot_raw": 2048,
                "pot_pct": 50,
                "ntc_raw": 1842,
                "ntc_pct": 45,
                "tracking_signal": False,
                "env_state": "comfortable",
                "interaction_hint": "object_near",
                "rgb_status": "near_object",
                "rgb_reason": "interaction_zone",
                "aht20_ok": True,
                "distance_ok": True,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["voice_state"] == "telemetry"
    assert data["sensors"]["temperature_c"] == 26.5
    assert data["sensors"]["humidity_pct"] == 48.2
    assert data["sensors"]["distance_cm"] == 31.4
    assert data["sensors"]["distance_zone"] == "near"
    assert data["sensors"]["pot_raw"] == 2048
    assert data["sensors"]["pot_pct"] == 50
    assert data["sensors"]["ntc_raw"] == 1842
    assert data["sensors"]["ntc_pct"] == 45
    assert data["sensors"]["tracking_signal"] is False
    assert data["sensors"]["env_state"] == "comfortable"
    assert data["sensors"]["interaction_hint"] == "object_near"
    assert data["sensors"]["rgb_status"] == "near_object"
    assert data["sensors"]["rgb_reason"] == "interaction_zone"


def test_hardware_telemetry_clears_stale_distance_when_disabled():
    client = make_client()

    client.post(
        "/api/hardware/telemetry",
        json={
            "device_id": "desktop-agent-001",
            "edge_id": "esp32s3-sense-001",
            "sensors": {
                "distance_ok": True,
                "distance_cm": 31.4,
            },
        },
    )
    response = client.post(
        "/api/hardware/telemetry",
        json={
            "device_id": "desktop-agent-001",
            "edge_id": "esp32s3-sense-001",
            "sensors": {
                "distance_enabled": False,
            },
        },
    )

    data = response.json()
    assert data["sensors"]["distance_enabled"] is False
    assert data["sensors"]["distance_ok"] is False
    assert "distance_cm" not in data["sensors"]


def test_websocket_text_loop_sends_protocol_events():
    client = make_client()
    register_card(client)

    with client.websocket_connect("/api/realtime/ws?device_id=desktop-agent-001&edge_id=esp32s3-sense-001") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["protocol"] == "smart-desktop-realtime-v1"

        ws.send_json({"type": "text", "text": "专注模式"})
        state_think = ws.receive_json()
        assistant = ws.receive_json()
        commands = ws.receive_json()
        state_idle = ws.receive_json()

    assert state_think == {"type": "state", "state": "think", "stage": "agent"}
    assert assistant["type"] == "assistant"
    assert "专注" in assistant["text"]
    assert commands["type"] == "stm32/commands"
    assert any(":NET:OLED:FOCUS 25 MIN" in line for line in commands["lines"])
    assert state_idle == {"type": "state", "state": "idle"}

    diagnostics = client.get("/api/realtime/diagnostics/desktop-agent-001").json()
    assert diagnostics["state"]["session_connected"] is False
    assert diagnostics["state"]["pending_action_count"] == len(diagnostics["queued_actions"]) + len(diagnostics["sent_actions"])


def test_ui_websocket_does_not_mark_edge_session_connected():
    client = make_client()

    with client.websocket_connect("/api/realtime/ws?device_id=desktop-agent-001") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"

        diagnostics = client.get("/api/realtime/diagnostics/desktop-agent-001").json()
        assert diagnostics["state"]["session_connected"] is False


def test_button_event_interrupts_audio_and_updates_diagnostics():
    client = make_client()

    response = client.post(
        "/api/hardware/button",
        json={"device_id": "desktop-agent-001", "line": "BT:BTN:KEY2:SHORT:120", "source": "stm32"},
    ).json()

    assert response["ok"] is True
    assert response["commands"][0].endswith(":NET:TTS:STOP")
    assert response["actions"][0]["type"] == "audio_stop"

    diagnostics = client.get("/api/realtime/diagnostics/desktop-agent-001").json()
    sensors = diagnostics["state"]["sensors"]
    assert sensors["last_button_line"] == "BT:BTN:KEY2:SHORT:120"
    assert sensors["last_button_duration_ms"] == 120
    assert sensors["interrupt_seq"] == 1


def test_realtime_inject_uses_same_text_loop():
    client = make_client()

    response = client.post("/api/realtime/inject", json={"text": "关闭风扇"}).json()

    assert response["device_id"] == "desktop-agent-001"
    assert any(":NET:FAN:OFF" in line for line in response["commands"])


def test_hardware_action_queues_ui_state_for_polling_when_no_session():
    client = make_client()

    response = client.post("/api/hardware/action", json={"type": "ui_state", "payload": {"state": "listen"}})

    assert response.status_code == 200
    data = response.json()
    assert data["commands"][0].endswith(":NET:UI:LISTEN")
    queued = client.get("/api/hardware/commands/desktop-agent-001").json()
    assert queued["commands"] == data["commands"]


def test_manual_lock_priority_blocks_lower_priority_ai_unlock():
    client = make_client()

    manual = client.post(
        "/api/hardware/action",
        json={"type": "lock_control", "payload": {"state": "on"}, "source": "web_manual"},
    ).json()
    chat = client.post("/api/chat", json={"device_id": "desktop-agent-001", "text": "解锁"}).json()

    assert any(":NET:LOCK:ON" in line for line in manual["commands"])
    assert manual["state"]["sensors"]["lock_control_source"] == "web_manual"
    assert manual["state"]["sensors"]["lock_control_priority"] == 100
    assert not any(":NET:LOCK:OFF" in line for line in chat["commands"])
    assert chat["state"]["sensors"]["lock_state"] == "on"
    assert chat["state"]["sensors"]["lock_control_skipped_source"] == "ai_chat"


def test_asr_upload_can_inject_text_loop():
    client = make_client()
    client.app.state.asr = FailIfCalledAsrClient()

    response = client.post(
        "/api/asr/transcribe",
        data={"device_id": "desktop-agent-001", "mock_text": "你是谁", "inject": "true"},
        files={"audio": ("sample.wav", b"RIFF....WAVEfmt data", "audio/wav")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["text"] == "你是谁"
    assert data["audio_bytes"] > 0
    assert data["state"]["last_asr_text"] == "你是谁"
    assert data["chat"]["reply"]
    assert any(line.startswith("NET:CMD:act_") for line in data["chat"]["commands"])


def test_asr_upload_uses_backend_paraformer_when_mock_text_is_empty():
    client = make_client(dashscope_api_key="test-key")
    stub = StubAsrClient(TranscriptionResult(ok=True, provider="dashscope_paraformer", text="打开风扇"))
    client.app.state.asr = stub

    response = client.post(
        "/api/asr/transcribe",
        data={"device_id": "desktop-agent-001", "inject": "true", "source": "esp32_mic"},
        files={"audio": ("sample.wav", make_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == "dashscope_paraformer"
    assert data["source"] == "esp32_mic"
    assert data["text"] == "打开风扇"
    assert data["state"]["voice_state"] == "asr_ok"
    assert data["state"]["sensors"]["last_asr_provider"] == "dashscope_paraformer"
    assert data["state"]["sensors"]["last_asr_at"]
    assert data["chat"]["reply"]
    assert any(":NET:FAN:ON:2" in line for line in data["chat"]["commands"])
    assert stub.calls and stub.calls[0]["filename"] == "sample.wav"
    assert Path(stub.calls[0]["audio_path"]).exists()


def test_asr_chunked_upload_reassembles_real_audio_and_injects():
    client = make_client(dashscope_api_key="test-key")
    stub = StubAsrClient(TranscriptionResult(ok=True, provider="dashscope_paraformer", text="打开风扇"))
    client.app.state.asr = stub
    wav = make_wav_bytes(frames=3200)
    first = wav[:256]
    upload_id = "test-upload-1"

    first_response = client.post(
        "/api/asr/transcribe/chunk",
        data={
            "upload_id": upload_id,
            "offset": "0",
            "total_size": str(len(wav)),
            "final": "false",
            "device_id": "desktop-agent-001",
            "inject": "true",
            "source": "esp32_mic_chunked",
            "audio_format": "wav",
            "sample_rate": "16000",
        },
        files={"chunk": ("chunk.bin", first, "application/octet-stream")},
    )

    assert first_response.status_code == 200
    assert first_response.json() == {"ok": True, "complete": False, "received": len(first)}

    duplicate_response = client.post(
        "/api/asr/transcribe/chunk",
        data={
            "upload_id": upload_id,
            "offset": "0",
            "total_size": str(len(wav)),
            "final": "false",
        },
        files={"chunk": ("chunk.bin", first, "application/octet-stream")},
    )

    assert duplicate_response.status_code == 200
    assert duplicate_response.json() == {"ok": True, "complete": False, "received": len(first)}

    final_response = client.post(
        "/api/asr/transcribe/chunk",
        data={
            "upload_id": upload_id,
            "offset": str(len(first)),
            "total_size": str(len(wav)),
            "final": "true",
            "device_id": "desktop-agent-001",
            "inject": "true",
            "source": "esp32_mic_chunked",
            "audio_format": "wav",
            "sample_rate": "16000",
        },
        files={"chunk": ("chunk.bin", wav[len(first) :], "application/octet-stream")},
    )

    assert final_response.status_code == 200
    data = final_response.json()
    assert data["ok"] is True
    assert data["provider"] == "dashscope_paraformer"
    assert data["source"] == "esp32_mic_chunked"
    assert data["audio_bytes"] == len(wav)
    assert data["text"] == "打开风扇"
    assert data["chat"]["reply"]
    assert stub.calls and stub.calls[0]["audio_bytes"] == len(wav)
    assert stub.calls[0]["filename"] == "esp32-mic.wav"
    assert Path(stub.calls[0]["audio_path"]).exists()


def test_asr_upload_returns_error_when_backend_asr_fails():
    client = make_client(dashscope_api_key="test-key")
    stub = StubAsrClient(TranscriptionResult(ok=False, provider="dashscope_paraformer", error="ASR request timeout"))
    client.app.state.asr = stub

    response = client.post(
        "/api/asr/transcribe",
        data={"device_id": "desktop-agent-001"},
        files={"audio": ("sample.wav", make_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["error"] == "ASR request timeout"
    assert data["chat"] is None
    assert data["state"]["voice_state"] == "asr_error"
    assert data["state"]["sensors"]["last_asr_error"] == "ASR request timeout"


def test_asr_upload_rejects_stereo_wav_for_esp32_path():
    client = make_client(dashscope_api_key="test-key")

    response = client.post(
        "/api/asr/transcribe",
        data={"device_id": "desktop-agent-001"},
        files={"audio": ("stereo.wav", make_wav_bytes(channels=2), "audio/wav")},
    )

    assert response.status_code == 400
    assert "mono audio" in response.json()["detail"]


def test_asr_recognized_injects_real_text_loop():
    client = make_client()

    response = client.post(
        "/api/asr/recognized",
        json={"device_id": "desktop-agent-001", "text": "打开风扇", "source": "browser_speech"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == "client_speech"
    assert data["text"] == "打开风扇"
    assert data["source"] == "browser_speech"
    assert data["state"]["last_asr_text"] == "打开风扇"
    assert data["chat"]["reply"]
    assert any(":NET:FAN:ON:2" in line for line in data["chat"]["commands"])
