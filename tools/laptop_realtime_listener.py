from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from array import array
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from laptop_mic_sidecar import (
    DEFAULT_BASE_URL,
    DEFAULT_DEVICE_ID,
    audio_stats,
    configure_text_output,
    diagnostics,
    list_audio_devices,
    parse_device,
    post_wav,
    request_json,
    wait_for_action_statuses,
)


DEFAULT_INPUT_DEVICE = "1"
DEFAULT_SOURCE = "laptop_realtime_listener"
DEFAULT_WAKE_PHRASES = ["灵宝灵宝", "你好灵宝", "在吗灵宝"]
DEFAULT_WAKE_ALIASES = [
    "灵宝你好",
    "灵宝在吗",
    "你好小灵宝",
    "小灵宝小灵宝",
    "小灵宝",
    "玲宝玲宝",
    "你好玲宝",
    "凌宝凌宝",
    "你好凌宝",
    "林宝林宝",
    "你好林宝",
    "灵保灵保",
    "你好灵保",
    "灵堡灵堡",
    "你好灵堡",
    "零宝零宝",
    "你好零宝",
]
DEFAULT_STOP_PHRASES = ["再见灵宝", "再见再见"]
DEFAULT_STOP_ALIASES = ["灵宝再见", "拜拜灵宝", "结束对话", "先这样吧"]
_LOCK_HANDLE: Any | None = None
_BACKEND_PROCESS: subprocess.Popen[bytes] | None = None


@dataclass
class RuntimeStatus:
    state: str = "STARTING"
    backend_online: bool = False
    backend_summary: str = "checking"
    device_summary: str = "checking"
    turn_count: int = 0
    conversation_active: bool = False
    last_asr_text: str = ""
    last_ack: str = ""
    last_error: str = ""
    last_audio: str = ""
    last_feedback: str = ""
    last_timing: str = ""
    current_light: str = ""
    current_rms: float = 0.0
    threshold: float = 0.0
    noise_floor: float = 0.0
    pending_action_count: int = 0
    feedback_texts: list[str] | None = None
    feedback_time: float = 0.0


def clear_screen(enabled: bool) -> None:
    if enabled and sys.stdout.isatty():
        os.system("cls")


def acquire_single_instance_lock() -> bool:
    global _LOCK_HANDLE
    lock_path = Path(".tmp") / "laptop_realtime_listener.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()).encode("ascii", errors="ignore"))
    handle.flush()
    _LOCK_HANDLE = handle
    return True


def health_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/health"


def backend_health(base_url: str, *, timeout: float = 2.0) -> dict[str, Any] | None:
    try:
        health = request_json("GET", health_url(base_url), timeout=timeout)
    except Exception:
        return None
    return health if health.get("status") == "ok" else None


def is_local_backend(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def candidate_project_roots() -> list[Path]:
    candidates: list[Path] = []
    cwd = Path.cwd().resolve()
    candidates.extend([cwd, cwd.parent])

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir, exe_dir.parent])
    else:
        script_dir = Path(__file__).resolve().parent
        candidates.extend([script_dir, script_dir.parent])

    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def locate_project_root(args: argparse.Namespace) -> Path | None:
    if args.project_root:
        root = Path(args.project_root).expanduser().resolve()
        return root if (root / "backend" / "app" / "main.py").exists() else None

    for root in candidate_project_roots():
        if (root / "backend" / "app" / "main.py").exists():
            return root
    return None


def backend_python_candidates(args: argparse.Namespace) -> list[list[str]]:
    candidates: list[list[str]] = []
    explicit = args.backend_python or os.environ.get("LINGBAO_BACKEND_PYTHON") or os.environ.get("PYTHON")
    if explicit:
        candidates.append([explicit])

    if not getattr(sys, "frozen", False):
        candidates.append([sys.executable])

    python_on_path = shutil.which("python")
    if python_on_path:
        candidates.append([python_on_path])

    py_launcher = shutil.which("py")
    if py_launcher:
        candidates.append([py_launcher, "-3"])

    unique: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        key = tuple(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def log_tail(path: Path, line_count: int = 25) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-line_count:])


def wait_for_backend(base_url: str, process: subprocess.Popen[bytes], timeout_seconds: float) -> bool:
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    while time.monotonic() < deadline:
        if backend_health(base_url, timeout=2.0):
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.5)
    return bool(backend_health(base_url, timeout=2.0))


def ensure_backend_ready(args: argparse.Namespace, status: RuntimeStatus) -> bool:
    global _BACKEND_PROCESS

    health = backend_health(args.base_url, timeout=2.0)
    if health:
        status.backend_online = True
        status.backend_summary = (
            f"{health.get('ai_provider')}/{health.get('ai_model')}, "
            f"cloud_ready={health.get('cloud_ready')}"
        )
        return True

    if not args.auto_start_backend:
        status.backend_online = False
        status.backend_summary = "offline; auto-start disabled"
        return False

    if not is_local_backend(args.base_url):
        status.backend_online = False
        status.backend_summary = "offline; auto-start only supports local backend URLs"
        return False

    project_root = locate_project_root(args)
    if project_root is None:
        status.backend_online = False
        status.backend_summary = "offline; project root not found"
        return False

    backend_dir = project_root / "backend"
    tmp_dir = project_root / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    for index, python_prefix in enumerate(backend_python_candidates(args), start=1):
        stdout_log = tmp_dir / f"backend-autostart-{stamp}-{index}.out.log"
        stderr_log = tmp_dir / f"backend-autostart-{stamp}-{index}.err.log"
        command = [
            *python_prefix,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            args.backend_bind_host,
            "--port",
            str(urlparse(args.base_url).port or 8083),
        ]

        creationflags = 0
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)

        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        print(f"[startup] Backend offline; starting backend with: {' '.join(command)}", flush=True)
        print(f"[startup] Backend logs: {stdout_log} / {stderr_log}", flush=True)
        try:
            with stdout_log.open("wb") as stdout, stderr_log.open("wb") as stderr:
                process = subprocess.Popen(
                    command,
                    cwd=backend_dir,
                    stdout=stdout,
                    stderr=stderr,
                    creationflags=creationflags,
                    env=env,
                )
        except OSError as exc:
            status.last_error = f"backend start failed with {python_prefix[0]}: {exc}"
            continue

        if wait_for_backend(args.base_url, process, args.backend_wait_seconds):
            _BACKEND_PROCESS = process
            refresh_backend_status(args, status)
            print(f"[startup] Backend health OK at {health_url(args.base_url)} (pid={process.pid})", flush=True)
            return True

        exit_code = process.poll()
        status.last_error = (
            f"backend did not become healthy"
            + (f"; exited {exit_code}" if exit_code is not None else "")
        )
        if exit_code is None:
            process.terminate()
        stderr_tail = log_tail(stderr_log)
        if stderr_tail:
            print("[startup] Backend stderr tail:", flush=True)
            print(stderr_tail, flush=True)

    return False


def wait_for_device_bridge(args: argparse.Namespace, status: RuntimeStatus) -> bool:
    if args.device_wait_seconds <= 0:
        return True

    deadline = time.monotonic() + args.device_wait_seconds
    while time.monotonic() < deadline:
        try:
            diag = diagnostics(args.base_url, args.device_id)
        except Exception as exc:
            status.device_summary = f"waiting: {exc}"
        else:
            state = diag.get("state") or {}
            status.pending_action_count = int(state.get("pending_action_count") or 0)
            status.device_summary = (
                f"session_connected={state.get('session_connected')}, "
                f"uart_ok={state.get('uart_ok')}, "
                f"pending={state.get('pending_action_count')}"
            )
            if state.get("session_connected"):
                return True

        status.state = "DEVICE_STARTUP"
        render_status(args, status)
        time.sleep(0.5)

    return False


def render_status(args: argparse.Namespace, status: RuntimeStatus, *, clear: bool = True) -> None:
    clear_screen(clear and args.dashboard)
    wake_alias_count = max(0, len(getattr(args, "wake_match_phrase", args.wake_phrase)) - len(args.wake_phrase))
    stop_alias_count = max(0, len(getattr(args, "stop_match_phrase", args.stop_phrase)) - len(args.stop_phrase))
    lines = [
        "Lingbao Voice Console",
        "=" * 22,
        f"script: ONLINE",
        f"state: {status.state}",
        f"conversation: {'ACTIVE' if status.conversation_active else 'SLEEP_WAIT_WAKE'}",
        f"backend: {'ONLINE' if status.backend_online else 'OFFLINE'} ({status.backend_summary})",
        f"device: {status.device_summary}",
        f"pending actions: {status.pending_action_count}",
        f"input mode: {args.input_mode}",
        f"audio input: READY, sample-rate={args.sample_rate}, channels={args.channels}",
        (
            "voice detector: "
            f"rms={status.current_rms:.1f}, noise={status.noise_floor:.1f}, threshold={status.threshold:.1f}"
        ),
        f"wake words: {', '.join(args.wake_phrase)}" + (f" (+{wake_alias_count} aliases)" if wake_alias_count else ""),
        f"stop words: {', '.join(args.stop_phrase)}" + (f" (+{stop_alias_count} aliases)" if stop_alias_count else ""),
        "route: voice -> ASR -> Qwen -> device ACK",
        f"turns: {status.turn_count}",
        f"last ASR: {status.last_asr_text or '-'}",
        f"last ACK: {status.last_ack or '-'}",
        f"last feedback: {status.last_feedback or '-'}",
        f"last timing: {status.last_timing or '-'}",
        f"light: {status.current_light or '-'}",
        f"last WAV: {status.last_audio or '-'}",
        f"last error: {status.last_error or '-'}",
        "",
        "Close this window or press Ctrl+C to stop.",
    ]
    print("\n".join(lines), flush=True)


def refresh_backend_status(args: argparse.Namespace, status: RuntimeStatus) -> None:
    try:
        health = request_json("GET", f"{args.base_url}/api/health", timeout=3)
        diag = diagnostics(args.base_url, args.device_id)
    except Exception as exc:
        status.backend_online = False
        status.backend_summary = str(exc)
        status.device_summary = "unavailable"
        return

    state = diag.get("state") or {}
    status.pending_action_count = int(state.get("pending_action_count") or 0)
    status.backend_online = True
    status.backend_summary = (
        f"{health.get('ai_provider')}/{health.get('ai_model')}, "
        f"cloud_ready={health.get('cloud_ready')}"
    )
    status.device_summary = (
        f"session_connected={state.get('session_connected')}, "
        f"uart_ok={state.get('uart_ok')}, "
        f"pending={state.get('pending_action_count')}"
    )
    last_ack = state.get("last_ack") or {}
    if last_ack.get("line"):
        status.last_ack = str(last_ack.get("line"))


def wait_until_backend_idle(args: argparse.Namespace, status: RuntimeStatus) -> None:
    started = time.monotonic()
    while True:
        refresh_backend_status(args, status)
        if status.pending_action_count <= 0:
            return
        if args.max_pending_wait_seconds >= 0 and time.monotonic() - started >= args.max_pending_wait_seconds:
            status.last_error = f"pending actions still {status.pending_action_count}; listening anyway"
            return
        status.state = "PENDING_ACTIONS"
        render_status(args, status)
        time.sleep(max(0.1, args.status_interval_seconds))


def latest_button_event(args: argparse.Namespace, status: RuntimeStatus) -> tuple[int, str]:
    diag = diagnostics(args.base_url, args.device_id)
    state = diag.get("state") or {}
    sensors = state.get("sensors") or {}
    status.pending_action_count = int(state.get("pending_action_count") or 0)
    line = str(sensors.get("last_button_line") or "")
    seq = int(sensors.get("last_button_seq") or 0)
    if line:
        status.last_feedback = line
    return seq, line


def pcm_rms(raw_pcm: bytes) -> float:
    samples = array("h")
    samples.frombytes(raw_pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def effective_speech_threshold(args: argparse.Namespace, noise_floor: float) -> float:
    if not args.auto_threshold:
        return args.speech_rms_threshold
    adaptive = noise_floor * args.noise_trigger_ratio + args.noise_trigger_margin
    return max(args.speech_rms_threshold, adaptive)


def effective_silence_threshold(args: argparse.Namespace, noise_floor: float, speech_threshold: float) -> float:
    if not args.auto_threshold:
        return args.silence_rms_threshold
    adaptive = noise_floor * args.silence_noise_ratio + args.silence_noise_margin
    return min(speech_threshold * 0.82, max(args.silence_rms_threshold, adaptive))


def save_wav(path: Path, raw_pcm: bytes, *, sample_rate: int, channels: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(raw_pcm)


def output_path(source: str, turn_count: int) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Path(".tmp") / "laptop_realtime_listener" / f"{stamp}-{turn_count:03d}-{source}.wav"


def action_ids_from_response(response: dict[str, Any]) -> list[str]:
    return [
        action.get("id")
        for action in (((response.get("chat") or {}).get("actions")) or [])
        if action.get("id")
    ]


def recent_action_statuses(after: dict[str, Any], action_ids: list[str]) -> dict[str, str | None]:
    expected = set(action_ids)
    return {
        item.get("id"): item.get("status")
        for item in (after.get("recent_actions") or [])
        if item.get("id") in expected
    }


def request_recognized_text(
    *,
    base_url: str,
    device_id: str,
    text: str,
    source: str,
) -> dict[str, Any]:
    return request_json(
        "POST",
        f"{base_url.rstrip('/')}/api/asr/recognized",
        {
            "device_id": device_id,
            "text": text,
            "source": source,
            "inject": True,
        },
        timeout=120,
    )


def enqueue_hardware_action(
    *,
    base_url: str,
    device_id: str,
    action_type: str,
    payload: dict[str, Any],
    timeout: float = 2.0,
) -> dict[str, Any]:
    return request_json(
        "POST",
        f"{base_url.rstrip('/')}/api/hardware/action",
        {
            "device_id": device_id,
            "type": action_type,
            "payload": payload,
            "mark_sent": True,
        },
        timeout=timeout,
    )


def action_ids_from_hardware_response(response: dict[str, Any]) -> list[str]:
    return [
        action.get("id")
        for action in (response.get("actions") or [])
        if action.get("id")
    ]


def send_wake_ack(args: argparse.Namespace, status: RuntimeStatus) -> None:
    action_ids: list[str] = []
    if args.wake_ack_oled:
        oled_response = enqueue_hardware_action(
            base_url=args.base_url,
            device_id=args.device_id,
            action_type="oled_display",
            payload={"text": args.wake_ack_oled},
            timeout=2.0,
        )
        action_ids.extend(action_ids_from_hardware_response(oled_response))
    if args.wake_ack_text:
        tts_response = enqueue_hardware_action(
            base_url=args.base_url,
            device_id=args.device_id,
            action_type="tts_speak",
            payload={"text": args.wake_ack_text},
            timeout=2.0,
        )
        action_ids.extend(action_ids_from_hardware_response(tts_response))

    if action_ids:
        after = wait_for_action_statuses(
            base_url=args.base_url,
            device_id=args.device_id,
            action_ids=action_ids,
            timeout_seconds=args.wake_ack_wait_seconds,
        )
        statuses = recent_action_statuses(after, action_ids)
        state = after.get("state") or {}
        last_ack = state.get("last_ack") or {}
        status.last_ack = str(last_ack.get("line") or statuses or "-")
        failed = {action_id: value for action_id, value in statuses.items() if value == "failed"}
        if failed:
            status.last_error = f"wake ack failed: {failed}"
    if args.wake_ack_text:
        status.feedback_texts = [args.wake_ack_text]
        status.feedback_time = time.monotonic()
        status.last_feedback = args.wake_ack_text


def set_status_light(args: argparse.Namespace, status: RuntimeStatus, light: str, reason: str) -> None:
    if not args.hardware_lights or status.current_light == light:
        return
    try:
        if light == "blue":
            enqueue_hardware_action(
                base_url=args.base_url,
                device_id=args.device_id,
                action_type="ui_state",
                payload={"state": "LISTEN"},
            )
        elif light == "green":
            enqueue_hardware_action(
                base_url=args.base_url,
                device_id=args.device_id,
                action_type="ui_state",
                payload={"state": "OUTPUT"},
            )
        status.current_light = light
    except Exception as exc:
        status.last_error = f"light {light} failed during {reason}: {exc}"


def normalize_echo_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def dedupe_phrases(phrases: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        normalized = normalize_echo_text(phrase)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(phrase)
    return deduped


def echo_similarity(left: str, right: str) -> float:
    normalized_left = normalize_echo_text(left)
    normalized_right = normalize_echo_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        shorter = min(len(normalized_left), len(normalized_right))
        longer = max(len(normalized_left), len(normalized_right))
        return shorter / max(1, longer)
    return difflib.SequenceMatcher(None, normalized_left, normalized_right).ratio()


def phrase_matches(text: str, phrases: list[str]) -> list[str]:
    normalized_text = normalize_echo_text(text)
    matched: list[str] = []
    for phrase in phrases:
        normalized_phrase = normalize_echo_text(phrase)
        if normalized_phrase and normalized_phrase in normalized_text:
            matched.append(phrase)
    return matched


def remove_phrases(text: str, phrases: list[str]) -> str:
    cleaned = text
    for phrase in phrases:
        cleaned = cleaned.replace(phrase, " ")
        normalized_phrase = normalize_echo_text(phrase)
        if normalized_phrase:
            loose_pattern = r"[\W_]*".join(re.escape(ch) for ch in normalized_phrase)
            cleaned = re.sub(loose_pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[，,。.!！？?、；;：:\s]+", " ", cleaned)
    return cleaned.strip()


def is_recent_feedback_echo(args: argparse.Namespace, status: RuntimeStatus, text: str) -> tuple[bool, float, str]:
    if not status.feedback_texts:
        return False, 0.0, ""
    if time.monotonic() - status.feedback_time > args.echo_filter_seconds:
        return False, 0.0, ""

    best_score = 0.0
    best_text = ""
    for feedback_text in status.feedback_texts:
        score = echo_similarity(text, feedback_text)
        if score > best_score:
            best_score = score
            best_text = feedback_text
    return best_score >= args.echo_similarity_threshold, best_score, best_text


def collect_feedback_texts(chat: dict[str, Any] | None) -> list[str]:
    if not chat:
        return []

    texts: list[str] = []
    for key in ("speech", "reply"):
        value = str(chat.get(key) or "").strip()
        if value:
            texts.append(value)

    for action in chat.get("actions") or []:
        if action.get("type") != "tts_speak":
            continue
        payload = action.get("payload") or {}
        text = str(payload.get("text") or "").strip()
        if text:
            texts.append(text)

    deduped: list[str] = []
    seen: set[str] = set()
    for text in texts:
        normalized = normalize_echo_text(text)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(text)
    return deduped


def estimate_feedback_guard_seconds(args: argparse.Namespace, feedback_texts: list[str]) -> float:
    if not feedback_texts:
        return args.no_tts_feedback_guard_seconds

    longest = max(feedback_texts, key=len)
    cjk_count = sum(1 for ch in longest if "\u4e00" <= ch <= "\u9fff")
    other_count = max(0, len(longest) - cjk_count)
    estimated = args.feedback_guard_base_seconds + cjk_count * args.feedback_guard_cjk_char_seconds
    estimated += other_count * args.feedback_guard_other_char_seconds
    return max(args.feedback_guard_min_seconds, min(args.feedback_guard_max_seconds, estimated))


def wait_feedback_guard(args: argparse.Namespace, status: RuntimeStatus, feedback_texts: list[str]) -> None:
    guard_seconds = estimate_feedback_guard_seconds(args, feedback_texts)
    status.feedback_texts = feedback_texts
    status.feedback_time = time.monotonic()
    status.last_feedback = feedback_texts[0] if feedback_texts else "no TTS feedback"
    if guard_seconds <= 0:
        return

    deadline = time.monotonic() + guard_seconds
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        status.state = f"FEEDBACK_GUARD {remaining:.1f}s"
        refresh_backend_status(args, status)
        render_status(args, status)
        time.sleep(min(args.status_interval_seconds, remaining))


def listen_for_utterance(args: argparse.Namespace, status: RuntimeStatus) -> tuple[bytes, dict[str, Any]]:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is required: python -m pip install sounddevice") from exc

    block_frames = max(1, int(args.sample_rate * args.block_ms / 1000))
    start_blocks = max(1, int(args.start_ms / args.block_ms))
    silence_blocks_needed = max(1, int(args.end_silence_ms / args.block_ms))
    pre_roll_blocks = max(1, int(args.pre_roll_ms / args.block_ms))
    min_blocks = max(1, int(args.min_record_seconds * 1000 / args.block_ms))
    max_blocks = max(1, int(args.max_record_seconds * 1000 / args.block_ms))

    pre_roll: deque[bytes] = deque(maxlen=pre_roll_blocks)
    speech_blocks = 0
    silence_blocks = 0
    recorded_blocks = 0
    recording = False
    audio = bytearray()
    last_render = 0.0
    noise_samples: deque[float] = deque(maxlen=max(10, int(args.noise_window_seconds * 1000 / args.block_ms)))

    status.state = "LISTENING"
    set_status_light(args, status, "blue", "listening")
    render_status(args, status)

    with sd.RawInputStream(
        samplerate=args.sample_rate,
        channels=args.channels,
        dtype="int16",
        device=parse_device(args.input_device),
        blocksize=block_frames,
    ) as stream:
        while True:
            block, overflowed = stream.read(block_frames)
            raw = bytes(block)
            rms = pcm_rms(raw)
            status.current_rms = rms
            if overflowed:
                status.last_error = "audio input overflow"

            if noise_samples:
                status.noise_floor = float(median(noise_samples))
            elif status.noise_floor <= 0:
                status.noise_floor = min(rms, args.silence_rms_threshold)
            speech_threshold = effective_speech_threshold(args, status.noise_floor)
            silence_threshold = effective_silence_threshold(args, status.noise_floor, speech_threshold)
            status.threshold = speech_threshold

            now = time.monotonic()
            if now - last_render >= args.status_interval_seconds:
                render_status(args, status)
                last_render = now

            if not recording:
                pre_roll.append(raw)
                if rms <= max(silence_threshold, speech_threshold * 0.65):
                    noise_samples.append(rms)
                if rms >= speech_threshold:
                    speech_blocks += 1
                else:
                    speech_blocks = 0

                if speech_blocks >= start_blocks:
                    recording = True
                    status.state = "RECORDING"
                    set_status_light(args, status, "blue", "recording")
                    render_status(args, status)
                    audio.extend(b"".join(pre_roll))
                    recorded_blocks = len(pre_roll)
                    silence_blocks = 0
                continue

            audio.extend(raw)
            recorded_blocks += 1
            if rms <= silence_threshold:
                silence_blocks += 1
            else:
                silence_blocks = 0

            enough_audio = recorded_blocks >= min_blocks
            heard_ending = enough_audio and silence_blocks >= silence_blocks_needed
            hit_limit = recorded_blocks >= max_blocks
            if heard_ending or hit_limit:
                stats_path = output_path(args.source, status.turn_count + 1)
                save_wav(stats_path, bytes(audio), sample_rate=args.sample_rate, channels=args.channels)
                stats = audio_stats(bytes(audio), sample_rate=args.sample_rate, channels=args.channels, path=stats_path)
                return bytes(audio), stats


def listen_for_ptt_utterance(args: argparse.Namespace, status: RuntimeStatus) -> tuple[bytes, dict[str, Any]]:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is required: python -m pip install sounddevice") from exc

    block_frames = max(1, int(args.sample_rate * args.block_ms / 1000))
    max_blocks = max(1, int(args.max_record_seconds * 1000 / args.block_ms))
    poll_seconds = max(0.03, float(args.ptt_poll_seconds))

    last_seq, _ = latest_button_event(args, status)
    status.state = "WAIT_KEY2_HOLD"
    set_status_light(args, status, "blue", "ptt_wait")
    render_status(args, status)

    last_render = 0.0
    while True:
        seq, line = latest_button_event(args, status)
        if seq != last_seq:
            last_seq = seq
            if "KEY2:HOLD_START" in line:
                break
        status.state = "WAIT_KEY2_HOLD"
        now = time.monotonic()
        if now - last_render >= args.status_interval_seconds:
            render_status(args, status)
            last_render = now
        time.sleep(poll_seconds)

    audio = bytearray()
    recorded_blocks = 0
    last_poll = 0.0
    status.state = "PTT_RECORDING"
    status.conversation_active = True
    set_status_light(args, status, "blue", "ptt_recording")
    render_status(args, status)

    with sd.RawInputStream(
        samplerate=args.sample_rate,
        channels=args.channels,
        dtype="int16",
        device=parse_device(args.input_device),
        blocksize=block_frames,
    ) as stream:
        while True:
            block, overflowed = stream.read(block_frames)
            raw = bytes(block)
            audio.extend(raw)
            recorded_blocks += 1
            status.current_rms = pcm_rms(raw)
            if overflowed:
                status.last_error = "audio input overflow"

            now = time.monotonic()
            if now - last_poll >= poll_seconds:
                seq, line = latest_button_event(args, status)
                last_poll = now
                if seq != last_seq:
                    last_seq = seq
                    if "KEY2:UP" in line:
                        break
                    if "KEY2:SHORT" in line:
                        audio.clear()
                        status.state = "PTT_CANCELLED"
                        render_status(args, status)
                        return listen_for_ptt_utterance(args, status)
                if now - last_render >= args.status_interval_seconds:
                    render_status(args, status)
                    last_render = now

            if recorded_blocks >= max_blocks:
                status.last_error = "PTT max record duration reached"
                break

    if not audio:
        raise RuntimeError("PTT recording ended without audio")
    stats_path = output_path(args.source, status.turn_count + 1)
    save_wav(stats_path, bytes(audio), sample_rate=args.sample_rate, channels=args.channels)
    stats = audio_stats(bytes(audio), sample_rate=args.sample_rate, channels=args.channels, path=stats_path)
    return bytes(audio), stats


def run_turn(args: argparse.Namespace, status: RuntimeStatus, audio: bytes, stats: dict[str, Any]) -> None:
    wav_path = Path(str(stats["path"]))
    status.last_audio = str(wav_path)
    status.state = "ASR_QWEN_ACK"
    set_status_light(args, status, "green", "asr")
    render_status(args, status)
    turn_started = time.perf_counter()
    asr_started = time.perf_counter()

    try:
        before = diagnostics(args.base_url, args.device_id)
        response = post_wav(
            base_url=args.base_url,
            device_id=args.device_id,
            wav_path=wav_path,
            inject=False,
            source=args.source,
            sample_rate=args.sample_rate,
            channels=args.channels,
        )
        asr_ms = int((time.perf_counter() - asr_started) * 1000)
        status.last_asr_text = str(response.get("text") or "")
        is_echo, echo_score, echo_text = is_recent_feedback_echo(args, status, status.last_asr_text)
        if is_echo:
            status.state = "ECHO_IGNORED"
            status.last_error = f"ignored likely device feedback echo, similarity={echo_score:.2f}"
            summary = {
                "ok": True,
                "turn": status.turn_count,
                "ignored": "device_feedback_echo",
                "echo_similarity": round(echo_score, 3),
                "asr_text": status.last_asr_text,
                "matched_feedback": echo_text,
                "audio": stats,
            }
            if args.debug_json:
                print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
            render_status(args, status)
            time.sleep(max(0.0, args.cooldown_seconds))
            return

        if not response.get("ok") or not status.last_asr_text.strip():
            status.state = "ASR_EMPTY"
            status.last_error = str(response.get("error") or "ASR completed without recognized text.")
            render_status(args, status)
            time.sleep(max(0.0, args.cooldown_seconds))
            return

        if args.input_mode == "ptt":
            status.conversation_active = True
        wake_matches = phrase_matches(status.last_asr_text, args.wake_match_phrase)
        stop_matches = phrase_matches(status.last_asr_text, args.stop_match_phrase)

        if not status.conversation_active:
            if not wake_matches:
                status.state = "SLEEP_WAIT_WAKE"
                status.last_error = "sleeping until wake word"
                render_status(args, status)
                time.sleep(max(0.0, args.cooldown_seconds))
                return

            status.conversation_active = True
            status.state = "WAKE_READY"
            status.last_error = ""
            command_text = remove_phrases(status.last_asr_text, args.wake_match_phrase)
            if not command_text:
                status.state = "WAKE_ACK"
                render_status(args, status)
                send_wake_ack(args, status)
                render_status(args, status)
                time.sleep(max(0.0, args.cooldown_seconds))
                return
            status.last_asr_text = command_text
        elif stop_matches and args.input_mode != "ptt":
            status.conversation_active = False
            status.state = "SLEEP_WAIT_WAKE"
            status.last_error = "stop word heard; sleeping until wake word"
            set_status_light(args, status, "blue", "wait_wake")
            render_status(args, status)
            time.sleep(max(0.0, args.cooldown_seconds))
            return

        status.state = "QWEN_ACK"
        set_status_light(args, status, "green", "qwen_ack")
        render_status(args, status)
        qwen_started = time.perf_counter()
        injected = request_recognized_text(
            base_url=args.base_url,
            device_id=args.device_id,
            text=status.last_asr_text,
            source=args.source,
        )
        qwen_ms = int((time.perf_counter() - qwen_started) * 1000)
        chat = injected.get("chat") or {}
        action_ids = action_ids_from_response(injected)
        ack_started = time.perf_counter()
        after = wait_for_action_statuses(
            base_url=args.base_url,
            device_id=args.device_id,
            action_ids=action_ids,
            timeout_seconds=args.wait_ack_seconds,
        )
        ack_wait_ms = int((time.perf_counter() - ack_started) * 1000)
        statuses = recent_action_statuses(after, action_ids)
        state = after.get("state") or {}
        last_ack = state.get("last_ack") or {}
        status.last_ack = str(last_ack.get("line") or statuses or "-")
        status.turn_count += 1
        status.last_error = str(injected.get("error") or response.get("error") or "")
        capture_ms = int(float(stats.get("duration_seconds") or 0) * 1000)
        total_ms = int(capture_ms + (time.perf_counter() - turn_started) * 1000)
        status.last_timing = (
            f"capture={capture_ms}ms, asr={asr_ms}ms, qwen={qwen_ms}ms, "
            f"ack_wait={ack_wait_ms}ms, total_to_ack={total_ms}ms"
        )
        summary = {
            "ok": bool(response.get("ok")),
            "turn": status.turn_count,
            "audio": stats,
            "asr": {
                "ok": response.get("ok"),
                "provider": response.get("provider"),
                "text": response.get("text"),
                "error": response.get("error"),
            },
            "actions": {
                "created": action_ids,
                "statuses": statuses,
                "ack_ok_count_before": before.get("state", {}).get("ack_ok_count"),
                "ack_ok_count_after": state.get("ack_ok_count"),
                "ack_err_count_after": state.get("ack_err_count"),
                "pending_action_count_after": state.get("pending_action_count"),
                "last_ack": last_ack,
            },
            "timing_ms": {
                "capture": capture_ms,
                "asr": asr_ms,
                "qwen_inject": qwen_ms,
                "ack_wait": ack_wait_ms,
                "total_to_ack": total_ms,
            },
            "feedback_guard_texts": collect_feedback_texts(chat),
            "note": "Laptop microphone temporary front-end only; ESP32S3 onboard mic remains separate.",
        }
        if args.debug_json:
            print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        wait_feedback_guard(args, status, collect_feedback_texts(chat))
    except Exception as exc:
        status.last_error = str(exc)
    finally:
        status.state = "COOLDOWN"
        refresh_backend_status(args, status)
        render_status(args, status)
        time.sleep(max(0.0, args.cooldown_seconds))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lingbao manual realtime listener. It uses VAD to capture each spoken utterance "
            "silently, uploads it to /api/asr/transcribe with inject=false for ASR and echo "
            "filtering, injects non-echo recognized text into Qwen, waits for ESP32S3/STM32 ACK, "
            "then returns to listening for continuous dialogue."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument("--auto-start-backend", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--backend-bind-host", default="0.0.0.0")
    parser.add_argument("--backend-wait-seconds", type=float, default=20.0)
    parser.add_argument("--device-wait-seconds", type=float, default=8.0)
    parser.add_argument("--backend-python", default="", help="Python executable used to auto-start backend.")
    parser.add_argument("--project-root", default="", help="Project root used to locate backend/.")
    parser.add_argument("--startup-check-only", action="store_true", help="Check/auto-start backend, then exit.")
    parser.add_argument("--input-device", default=DEFAULT_INPUT_DEVICE)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--input-mode", choices=["vad", "ptt"], default="vad")
    parser.add_argument("--ptt-poll-seconds", type=float, default=0.08)
    parser.add_argument("--wake-phrase", action="append", default=[], help="Wake phrase. Repeatable.")
    parser.add_argument("--stop-phrase", action="append", default=[], help="Stop phrase. Repeatable.")
    parser.add_argument("--wake-alias", action="append", default=[], help="Extra wake phrase alias. Repeatable.")
    parser.add_argument("--stop-alias", action="append", default=[], help="Extra stop phrase alias. Repeatable.")
    parser.add_argument("--block-ms", type=int, default=60)
    parser.add_argument("--pre-roll-ms", type=int, default=500)
    parser.add_argument("--start-ms", type=int, default=120)
    parser.add_argument("--end-silence-ms", type=int, default=650)
    parser.add_argument("--min-record-seconds", type=float, default=0.55)
    parser.add_argument("--max-record-seconds", type=float, default=6.0)
    parser.add_argument("--speech-rms-threshold", type=float, default=95.0)
    parser.add_argument("--silence-rms-threshold", type=float, default=55.0)
    parser.add_argument("--auto-threshold", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--noise-window-seconds", type=float, default=2.0)
    parser.add_argument("--noise-trigger-ratio", type=float, default=2.2)
    parser.add_argument("--noise-trigger-margin", type=float, default=28.0)
    parser.add_argument("--silence-noise-ratio", type=float, default=1.35)
    parser.add_argument("--silence-noise-margin", type=float, default=16.0)
    parser.add_argument("--cooldown-seconds", type=float, default=0.12)
    parser.add_argument("--wait-ack-seconds", type=float, default=6.0)
    parser.add_argument("--max-pending-wait-seconds", type=float, default=2.0)
    parser.add_argument("--wake-ack-text", default="我在", help="Short device TTS after wake-only phrase. Empty disables.")
    parser.add_argument("--wake-ack-oled", default="VOICE READY", help="OLED text after wake-only phrase. Empty disables.")
    parser.add_argument("--wake-ack-wait-seconds", type=float, default=3.0)
    parser.add_argument("--feedback-guard-base-seconds", type=float, default=0.35)
    parser.add_argument("--feedback-guard-cjk-char-seconds", type=float, default=0.12)
    parser.add_argument("--feedback-guard-other-char-seconds", type=float, default=0.05)
    parser.add_argument("--feedback-guard-min-seconds", type=float, default=0.8)
    parser.add_argument("--feedback-guard-max-seconds", type=float, default=3.2)
    parser.add_argument("--no-tts-feedback-guard-seconds", type=float, default=0.15)
    parser.add_argument("--echo-filter-seconds", type=float, default=10.0)
    parser.add_argument("--echo-similarity-threshold", type=float, default=0.72)
    parser.add_argument("--status-interval-seconds", type=float, default=0.25)
    parser.add_argument("--hardware-lights", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--dashboard", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--debug-json", action="store_true", help="Print per-turn debug JSON.")
    parser.add_argument("--max-utterances", type=int, default=0, help="Stop after N captured utterances. 0 means keep listening.")
    parser.add_argument("--list-devices", action="store_true")
    return parser.parse_args()


def main() -> int:
    configure_text_output()
    args = parse_args()
    args.base_url = args.base_url.rstrip("/")
    if args.input_mode == "ptt" and args.source == DEFAULT_SOURCE:
        args.source = "laptop_ptt_listener"
    if not args.wake_phrase:
        args.wake_phrase = DEFAULT_WAKE_PHRASES
    if not args.stop_phrase:
        args.stop_phrase = DEFAULT_STOP_PHRASES
    if not args.wake_alias:
        args.wake_alias = DEFAULT_WAKE_ALIASES
    if not args.stop_alias:
        args.stop_alias = DEFAULT_STOP_ALIASES
    args.wake_match_phrase = dedupe_phrases(args.wake_phrase + args.wake_alias)
    args.stop_match_phrase = dedupe_phrases(args.stop_phrase + args.stop_alias)

    if args.list_devices:
        return list_audio_devices()
    if args.channels != 1:
        print("ERROR: backend ASR path currently expects mono audio; use --channels 1.", file=sys.stderr)
        return 2
    if args.speech_rms_threshold <= 0 or args.silence_rms_threshold <= 0:
        print("ERROR: RMS thresholds must be positive.", file=sys.stderr)
        return 2
    if not acquire_single_instance_lock():
        print("ERROR: another Lingbao realtime listener is already running. Close it before starting a new one.", file=sys.stderr)
        try:
            input("Press Enter to close...")
        except EOFError:
            pass
        return 2

    status = RuntimeStatus()
    status.state = "BACKEND_STARTUP"
    render_status(args, status)
    if not ensure_backend_ready(args, status):
        status.state = "BACKEND_OFFLINE"
        render_status(args, status)
        print("ERROR: backend is not online, and auto-start did not succeed.", file=sys.stderr)
        print("Check the backend logs under .tmp, then press Enter to close.", file=sys.stderr)
        try:
            input()
        except EOFError:
            pass
        return 3

    wait_for_device_bridge(args, status)

    if args.startup_check_only:
        status.state = "STARTUP_CHECK_OK"
        render_status(args, status)
        return 0

    if args.input_mode == "ptt":
        print("[privacy] PTT mode records only while KEY2 is held on the STM32 board.", flush=True)
    else:
        print("[privacy] Microphone listening will start now because you opened the realtime listener.", flush=True)
        print("[privacy] The listener is silent: no app beep, no cue sound.", flush=True)

    captured_utterances = 0
    try:
        while True:
            refresh_backend_status(args, status)
            wait_until_backend_idle(args, status)
            render_status(args, status)
            if args.input_mode == "ptt":
                _audio, stats = listen_for_ptt_utterance(args, status)
                status.conversation_active = True
            else:
                _audio, stats = listen_for_utterance(args, status)
            captured_utterances += 1
            run_turn(args, status, _audio, stats)
            if args.max_utterances > 0 and captured_utterances >= args.max_utterances:
                status.state = "STOPPED_MAX_UTTERANCES"
                render_status(args, status)
                return 0
    except KeyboardInterrupt:
        status.state = "STOPPED"
        render_status(args, status)
        return 130
    except (OSError, URLError, HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
        status.state = "ERROR"
        status.last_error = str(exc)
        render_status(args, status)
        print("Press Enter to close...", flush=True)
        try:
            input()
        except EOFError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
