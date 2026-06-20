import importlib.util
import sys
from pathlib import Path


def load_protocol_module():
    path = Path(__file__).resolve().parents[2] / "firmware" / "stm32" / "protocol" / "protocol_reference.py"
    spec = importlib.util.spec_from_file_location("protocol_reference", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_wrapped_stm32_command_parser_contract():
    protocol = load_protocol_module()

    parsed = protocol.parse_line("NET:CMD:act_123:NET:TTSHEX:E4BDA0E5A5BD")

    assert parsed.wrapped is True
    assert parsed.action_id == "act_123"
    assert parsed.command == "NET:TTSHEX:E4BDA0E5A5BD"
    assert protocol.ack_for("NET:CMD:act_123:NET:TTSHEX:E4BDA0E5A5BD") == "BT:ACK:act_123:OK"


def test_direct_debug_command_parser_contract():
    protocol = load_protocol_module()

    parsed = protocol.parse_line("NET:UART?")

    assert parsed.wrapped is False
    assert parsed.action_id is None
    assert parsed.command == "NET:UART?"
    assert protocol.ack_for("NET:UART?", ok=False) == "BT:ERR"
