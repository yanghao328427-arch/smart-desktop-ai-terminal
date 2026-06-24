from tools.esp32_hf_relay import allowed_path, upstream_ws_url
from fastapi.testclient import TestClient
from tools.esp32_hf_relay import create_app


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


def test_relay_builds_filtered_upstream_websocket_url():
    assert upstream_ws_url(
        "https://example.test",
        "device_id=desktop-agent-001&edge_id=esp32s3-sense-001&ignored=secret",
    ) == (
        "wss://example.test/api/realtime/ws"
        "?device_id=desktop-agent-001&edge_id=esp32s3-sense-001"
    )


def test_relay_health_reports_hybrid_mode():
    client = TestClient(create_app("https://example.test", 5))
    response = client.get("/relay/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "mode": "http+websocket",
        "upstream": "https://example.test",
        "rate_limit_cooldown_seconds": 0,
    }
