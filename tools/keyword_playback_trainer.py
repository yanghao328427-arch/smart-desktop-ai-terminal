from __future__ import annotations

import argparse
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PHRASES = ["灵宝灵宝", "你好灵宝", "灵宝你好", "小灵宝小灵宝"]
DEFAULT_STOP_PHRASES = ["再见灵宝", "再见再见", "灵宝再见", "拜拜灵宝"]
DEFAULT_DETECT_REGEX = (
    r"wake|wakeup|hotword|keyword|kws|唤醒|识别|recognized|ASR OK|"
    r"灵宝|玲宝|凌宝|林宝|BT:ACK|NET:UI:LISTEN|NET:UI:OUTPUT"
)


@dataclass
class Hit:
    line: str
    phrase: str
    cycle: int


def ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def powershell_exe() -> str:
    return "powershell.exe" if sys.platform.startswith("win") else "pwsh"


def speak_phrase(text: str, *, rate: int, volume: int, voice_contains: str = "") -> None:
    voice_filter = ""
    if voice_contains:
        voice_filter = f"""
$voice = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Name -like {ps_literal('*' + voice_contains + '*')} }} | Select-Object -First 1
if ($voice) {{ $s.SelectVoice($voice.VoiceInfo.Name) }}
"""
    command = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Volume = {max(0, min(100, volume))}
$s.Rate = {max(-10, min(10, rate))}
{voice_filter}
$s.Speak({ps_literal(text)})
$s.Dispose()
"""
    subprocess.run(
        [powershell_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=True,
    )


def list_voices() -> int:
    command = """
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.GetInstalledVoices() | ForEach-Object {
  $v = $_.VoiceInfo
  '{0} | {1} | {2}' -f $v.Name, $v.Culture, $v.Gender
}
$s.Dispose()
"""
    completed = subprocess.run(
        [powershell_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout.rstrip(), flush=True)
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr, flush=True)
    return completed.returncode


def serial_reader(
    *,
    port_name: str,
    baud: int,
    line_queue: queue.Queue[str],
    write_queue: queue.Queue[str],
    ready: threading.Event,
    stop: threading.Event,
    open_delay: float,
) -> None:
    try:
        import serial
    except ImportError:
        line_queue.put("[serial] pyserial is not installed; run: python -m pip install pyserial")
        stop.set()
        return

    try:
        with serial.Serial(port_name, baud, timeout=0.2) as port:
            if open_delay > 0:
                time.sleep(open_delay)
            line_queue.put(f"[serial] monitoring {port_name} at {baud}")
            ready.set()
            while not stop.is_set():
                while True:
                    try:
                        line = write_queue.get_nowait()
                    except queue.Empty:
                        break
                    port.write((line + "\n").encode("utf-8"))
                    port.flush()
                    line_queue.put(f"[serial tx] {line}")
                try:
                    data = port.readline()
                except serial.SerialException as exc:
                    line_queue.put(f"[serial] read error: {exc}")
                    stop.set()
                    return
                if data:
                    line_queue.put(data.decode("utf-8", errors="replace").rstrip())
    except Exception as exc:
        line_queue.put(f"[serial] open error: {exc}")
        stop.set()


def drain_serial(
    *,
    line_queue: queue.Queue[str],
    detect: re.Pattern[str],
    log_file: Path,
    current_phrase: str,
    current_cycle: int,
) -> list[Hit]:
    hits: list[Hit] = []
    while True:
        try:
            line = line_queue.get_nowait()
        except queue.Empty:
            return hits
        print(line, flush=True)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        if detect.search(line):
            hits.append(Hit(line=line, phrase=current_phrase, cycle=current_cycle))
            print(f"[hit] cycle={current_cycle} phrase={current_phrase} line={line}", flush=True)


def build_phrases(args: argparse.Namespace) -> list[str]:
    phrases = list(args.phrase or DEFAULT_PHRASES)
    if args.include_stop_phrases:
        phrases.extend(args.stop_phrase or DEFAULT_STOP_PHRASES)
    seen: set[str] = set()
    deduped: list[str] = []
    for phrase in phrases:
        normalized = re.sub(r"[\W_]+", "", phrase, flags=re.UNICODE).casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(phrase)
    return deduped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Play Lingbao wake words through the laptop speaker for laptop-microphone listener "
            "calibration. Optional serial monitoring is for diagnostics only; this does not train "
            "an embedded wake-word model."
        )
    )
    parser.add_argument("--phrase", action="append", default=[], help="Phrase to play. Repeatable.")
    parser.add_argument("--include-stop-phrases", action="store_true")
    parser.add_argument("--stop-phrase", action="append", default=[], help="Stop phrase to include when enabled.")
    parser.add_argument("--cycles", type=int, default=20, help="Playback cycles. 0 means forever.")
    parser.add_argument("--interval", type=float, default=0.9, help="Seconds between phrases.")
    parser.add_argument("--cycle-pause", type=float, default=1.5, help="Seconds between cycles.")
    parser.add_argument("--rate", type=int, default=-3, help="Windows TTS rate, -10 to 10.")
    parser.add_argument("--volume", type=int, default=95, help="Windows TTS volume, 0 to 100.")
    parser.add_argument("--voice-contains", default="", help="Use a Windows TTS voice whose name contains this text.")
    parser.add_argument("--port", default="", help="Optional serial port to monitor, for example COM8.")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--open-delay", type=float, default=8.0, help="Delay after opening serial. COM8 may reset ESP32S3.")
    parser.add_argument("--detect-regex", default=DEFAULT_DETECT_REGEX)
    parser.add_argument("--until-hits", type=int, default=0, help="Stop after this many detected serial hits. 0 disables.")
    parser.add_argument(
        "--line-before-phrase",
        action="append",
        default=[],
        help="Serial line to send before each phrase, for example CFG:MIC:REC:ASRONLY. Repeatable.",
    )
    parser.add_argument("--line-delay", type=float, default=0.6, help="Seconds to wait after sending serial lines.")
    parser.add_argument("--post-listen-seconds", type=float, default=0.7, help="Drain serial after each spoken phrase.")
    parser.add_argument("--dry-run", action="store_true", help="Print playback plan without speaking.")
    parser.add_argument("--list-voices", action="store_true", help="List installed Windows TTS voices and exit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_voices:
        return list_voices()

    phrases = build_phrases(args)
    detect = re.compile(args.detect_regex, re.IGNORECASE)
    log_file = Path(".tmp") / "keyword_playback_trainer" / f"{time.strftime('%Y%m%d-%H%M%S')}.log"

    print("Lingbao laptop-listener keyword calibration", flush=True)
    print("This repeats audio from the laptop speaker for the laptop microphone listener.", flush=True)
    print("It does not prove or train ESP32S3 onboard microphone wake-word recognition.", flush=True)
    print(f"phrases: {', '.join(phrases)}", flush=True)
    print(f"cycles: {'forever' if args.cycles == 0 else args.cycles}", flush=True)
    print(f"log: {log_file}", flush=True)
    if args.port:
        print(f"serial: {args.port} @ {args.baud}, detect={args.detect_regex}", flush=True)

    if args.dry_run:
        return 0

    stop = threading.Event()
    ready = threading.Event()
    line_queue: queue.Queue[str] = queue.Queue()
    write_queue: queue.Queue[str] = queue.Queue()
    serial_thread: threading.Thread | None = None
    if args.port:
        serial_thread = threading.Thread(
            target=serial_reader,
            kwargs={
                "port_name": args.port,
                "baud": args.baud,
                "line_queue": line_queue,
                "write_queue": write_queue,
                "ready": ready,
                "stop": stop,
                "open_delay": args.open_delay,
            },
            daemon=True,
        )
        serial_thread.start()
        if not ready.wait(timeout=max(2.0, args.open_delay + 5.0)):
            print("[serial] not ready yet; continuing anyway.", flush=True)

    total_hits = 0
    cycle = 0
    try:
        while args.cycles == 0 or cycle < args.cycles:
            cycle += 1
            for phrase in phrases:
                if args.line_before_phrase:
                    if not args.port:
                        print("ERROR: --line-before-phrase requires --port.", file=sys.stderr)
                        return 2
                    for line in args.line_before_phrase:
                        write_queue.put(line)
                    time.sleep(max(0.0, args.line_delay))
                    hits = drain_serial(
                        line_queue=line_queue,
                        detect=detect,
                        log_file=log_file,
                        current_phrase=phrase,
                        current_cycle=cycle,
                    )
                    total_hits += len(hits)
                print(f"[play] cycle={cycle} phrase={phrase}", flush=True)
                speak_phrase(phrase, rate=args.rate, volume=args.volume, voice_contains=args.voice_contains)
                deadline = time.monotonic() + max(0.0, args.post_listen_seconds)
                while time.monotonic() < deadline:
                    hits = drain_serial(
                        line_queue=line_queue,
                        detect=detect,
                        log_file=log_file,
                        current_phrase=phrase,
                        current_cycle=cycle,
                    )
                    total_hits += len(hits)
                    if args.until_hits and total_hits >= args.until_hits:
                        print(f"[done] detected {total_hits} hits; stopping.", flush=True)
                        stop.set()
                        return 0
                    time.sleep(0.1)
                hits = drain_serial(
                    line_queue=line_queue,
                    detect=detect,
                    log_file=log_file,
                    current_phrase=phrase,
                    current_cycle=cycle,
                )
                total_hits += len(hits)
                if args.until_hits and total_hits >= args.until_hits:
                    print(f"[done] detected {total_hits} hits; stopping.", flush=True)
                    stop.set()
                    return 0
                time.sleep(max(0.0, args.interval))
            time.sleep(max(0.0, args.cycle_pause))
    except KeyboardInterrupt:
        print("\n[stop] playback stopped by user.", flush=True)
        return 130
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: TTS playback failed: {exc}", file=sys.stderr)
        return 1
    finally:
        stop.set()
        if serial_thread:
            serial_thread.join(timeout=1)

    print(f"[done] completed cycles={cycle}, detected_hits={total_hits}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
