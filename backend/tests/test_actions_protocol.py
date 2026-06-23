from app.actions import SYN6288_NATURAL_PREFIX, command_from_action
from app.schemas import ActionSpec


def decode_tts_command(command: str) -> str:
    assert command.startswith("NET:TTSHEX:")
    return bytes.fromhex(command.removeprefix("NET:TTSHEX:")).decode("utf-8")


def test_tts_action_uses_ascii_safe_hex_payload():
    command = command_from_action(ActionSpec(type="tts_speak", payload={"text": "你好 UART"}))
    text = decode_tts_command(command)

    assert text == f"{SYN6288_NATURAL_PREFIX}你好 UART。"


def test_tts_action_adds_syn6288_controls_and_light_pacing():
    command = command_from_action(ActionSpec(type="tts_speak", payload={"text": "好的我来打开风扇"}))
    text = decode_tts_command(command)

    assert text == f"{SYN6288_NATURAL_PREFIX}好的，我来打开风扇。"


def test_tts_action_removes_fragile_speech_symbols():
    command = command_from_action(ActionSpec(type="tts_speak", payload={"text": "记得，你刚才问了“你是谁？”～🙂"}))
    text = decode_tts_command(command)

    assert "“" not in text
    assert "”" not in text
    assert "～" not in text
    assert "🙂" not in text
    assert text.startswith(f"{SYN6288_NATURAL_PREFIX}记得，你刚才问了")
    assert len(text.encode("utf-8")) <= 30


def test_volume_action_supports_absolute_and_relative_levels():
    assert command_from_action(ActionSpec(type="volume_control", payload={"level": 8})) == "NET:VOLUME:8"
    assert command_from_action(ActionSpec(type="volume_control", payload={"level": 99})) == "NET:VOLUME:16"
    assert command_from_action(ActionSpec(type="volume_control", payload={"level": "down"})) == "NET:VOLUME:DOWN"


def test_servo_action_uses_bounded_angle_command():
    assert command_from_action(ActionSpec(type="servo_action", payload={"angle": 45})) == "NET:SERVO:45"
    assert command_from_action(ActionSpec(type="servo_action", payload={"angle": 240})) == "NET:SERVO:180"
    assert command_from_action(ActionSpec(type="servo_action", payload={"action": "close"})) == "NET:SERVO:0"


def test_buzzer_music_action_uses_known_presets():
    assert command_from_action(ActionSpec(type="buzzer_music", payload={"preset": "birthday"})) == "NET:MUSIC:BIRTHDAY"
    assert command_from_action(ActionSpec(type="buzzer_music", payload={"preset": "victory"})) == "NET:MUSIC:SUCCESS"
    assert command_from_action(ActionSpec(type="buzzer_music", payload={"preset": "stop"})) == "NET:MUSIC:STOP"
    assert command_from_action(ActionSpec(type="buzzer_music", payload={"preset": "raw:bad"})) == "NET:MUSIC:SUCCESS"


def test_ui_state_action_uses_stm32_ui_commands():
    assert command_from_action(ActionSpec(type="ui_state", payload={"state": "listening"})) == "NET:UI:LISTEN"
    assert command_from_action(ActionSpec(type="ui_state", payload={"state": "output"})) == "NET:UI:OUTPUT"
    assert command_from_action(ActionSpec(type="ui_state", payload={"state": "bad"})) == "NET:UI:IDLE"


def test_audio_stop_action_uses_tts_stop_command():
    assert command_from_action(ActionSpec(type="audio_stop", payload={})) == "NET:TTS:STOP"


def test_user_context_action_uses_protocol_safe_fields():
    command = command_from_action(
        ActionSpec(
            type="user_context",
            payload={"user_id": "user:alice 01", "uid": "04:A1:B2:C3", "mode": "study"},
        )
    )

    assert command == "NET:UI:USER:user_alice_01:04_A1_B2_C3:STUDY"
