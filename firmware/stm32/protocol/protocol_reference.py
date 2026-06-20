from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedCommand:
    action_id: str | None
    command: str
    wrapped: bool


def parse_line(line: str) -> ParsedCommand:
    value = line.strip()
    if not value.startswith("NET:CMD:"):
        return ParsedCommand(action_id=None, command=value, wrapped=False)

    prefix_len = len("NET:CMD:")
    marker = ":NET:"
    marker_index = value.find(marker, prefix_len)
    if marker_index < 0:
        return ParsedCommand(action_id=None, command="", wrapped=True)

    action_id = value[prefix_len:marker_index]
    command = value[marker_index + 1 :]
    return ParsedCommand(action_id=action_id, command=command, wrapped=True)


def ack_for(line: str, ok: bool = True) -> str:
    parsed = parse_line(line)
    if parsed.wrapped and parsed.action_id:
        return f"BT:ACK:{parsed.action_id}:{'OK' if ok else 'ERR'}"
    return "BT:OK" if ok else "BT:ERR"
