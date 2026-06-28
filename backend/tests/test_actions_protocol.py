from app.actions import SYN6288_NATURAL_PREFIX, WRAPPED_TTS_MAX_CHARS, command_from_action, split_tts_text, wrap_command
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
    assert len(text.encode("utf-8")) <= 90


def test_tts_action_splits_at_complete_sentences_without_losing_the_reply():
    chunks = split_tts_text("我不偏爱谁。他们都很厉害！")

    assert chunks == ["我不偏爱谁。", "他们都很厉害！"]
    for chunk in chunks:
        command = command_from_action(ActionSpec(type="tts_speak", payload={"text": chunk}))
        wrapped = wrap_command("act_123456789abc", command)
        assert decode_tts_command(f"NET:TTSHEX:{wrapped.split(':NET:TTSHEX:', 1)[1]}") == chunk
        assert len(wrapped) <= WRAPPED_TTS_MAX_CHARS


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


def test_telemetry_request_action_is_read_only():
    assert command_from_action(ActionSpec(type="telemetry_request", payload={})) == "NET:TELEMETRY?"


def test_self_check_probe_uses_compatible_uart_ping():
    assert command_from_action(ActionSpec(type="self_check_probe", payload={})) == "NET:UART?"


def test_user_context_action_uses_protocol_safe_fields():
    command = command_from_action(
        ActionSpec(
            type="user_context",
            payload={"user_id": "user:alice 01", "uid": "04:A1:B2:C3", "mode": "study"},
        )
    )

    assert command == "NET:UI:USER:user_alice_01:04_A1_B2_C3:STUDY"
