from tools.esp32_hf_relay import allowed_path


def test_relay_allows_required_device_paths():
    assert allowed_path("POST", "/api/hardware/telemetry")
    assert allowed_path("POST", "/api/hardware/heartbeat")
    assert allowed_path("POST", "/api/hardware/ack")
    assert allowed_path("POST", "/api/rfid/scan")
    assert allowed_path("GET", "/api/hardware/commands/desktop-agent-001")


def test_relay_rejects_unrelated_or_nested_paths():
    assert not allowed_path("POST", "/api/chat")
    assert not allowed_path("POST", "/api/users")
    assert not allowed_path("GET", "/api/hardware/commands/")
    assert not allowed_path("GET", "/api/hardware/commands/device/nested")
