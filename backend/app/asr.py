from __future__ import annotations

import asyncio
import io
import json
import re
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import websockets

from .config import Settings

SUPPORTED_AUDIO_FORMATS = {"pcm", "wav", "mp3", "opus", "speex", "aac", "amr"}
DEFAULT_CHUNK_SIZE = 4096


@dataclass
class AudioMeta:
    content: bytes
    format: str
    sample_rate: int
    channels: int | None = None


@dataclass
class TranscriptionResult:
    ok: bool
    provider: str
    text: str = ""
    error: str | None = None


class BaseAsrClient:
    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "",
        content_type: str = "",
        audio_format: str = "",
        sample_rate: int | None = None,
        channels: int | None = None,
        audio_path: str = "",
    ) -> TranscriptionResult:
        raise NotImplementedError


class UnavailableAsrClient(BaseAsrClient):
    def __init__(self, settings: Settings) -> None:
        self.provider = settings.asr_provider

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "",
        content_type: str = "",
        audio_format: str = "",
        sample_rate: int | None = None,
        channels: int | None = None,
        audio_path: str = "",
    ) -> TranscriptionResult:
        return TranscriptionResult(
            ok=False,
            provider=self.provider,
            error="ASR provider is not configured on the backend.",
        )


class DashScopeParaformerClient(BaseAsrClient):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "",
        content_type: str = "",
        audio_format: str = "",
        sample_rate: int | None = None,
        channels: int | None = None,
        audio_path: str = "",
    ) -> TranscriptionResult:
        meta = build_audio_meta(
            audio,
            filename=filename,
            content_type=content_type,
            audio_format=audio_format,
            sample_rate=sample_rate,
            channels=channels,
        )
        try:
            text = await self._transcribe_meta(meta)
        except Exception as exc:
            return TranscriptionResult(
                ok=False,
                provider=self.settings.asr_provider,
                error=str(exc) or exc.__class__.__name__,
            )
        return TranscriptionResult(
            ok=bool(text),
            provider=self.settings.asr_provider,
            text=text,
            error=None if text else "ASR completed without recognized text.",
        )

    async def _transcribe_meta(self, meta: AudioMeta) -> str:
        task_id = str(uuid4())
        run_task = {
            "header": {
                "action": "run-task",
                "task_id": task_id,
                "streaming": "duplex",
            },
            "payload": {
                "task_group": "audio",
                "task": "asr",
                "function": "recognition",
                "model": self.settings.asr_model,
                "parameters": {
                    "format": meta.format,
                    "sample_rate": meta.sample_rate,
                    "max_sentence_silence": 800,
                },
                "input": {},
            },
        }
        if self.settings.asr_language_hint:
            run_task["payload"]["parameters"]["language_hints"] = [self.settings.asr_language_hint]

        finish_task = {
            "header": {
                "action": "finish-task",
                "task_id": task_id,
                "streaming": "duplex",
            },
            "payload": {"input": {}},
        }
        headers = {"Authorization": f"Bearer {self.settings.dashscope_api_key}"}
        final_sentences: list[str] = []
        partial_text = ""

        async with websockets.connect(
            self.settings.asr_ws_url,
            additional_headers=headers,
            open_timeout=10,
            close_timeout=10,
            max_size=None,
        ) as websocket:
            await websocket.send(json.dumps(run_task))
            await self._await_task_started(websocket, task_id)

            for chunk in chunk_audio(meta.content):
                await websocket.send(chunk)

            await websocket.send(json.dumps(finish_task))

            while True:
                message = await asyncio.wait_for(websocket.recv(), timeout=20)
                if isinstance(message, bytes):
                    continue
                event = json.loads(message)
                header = event.get("header") or {}
                event_name = header.get("event", "")
                if event_name == "result-generated":
                    sentence = (((event.get("payload") or {}).get("output") or {}).get("sentence") or {})
                    text = normalize_transcript(sentence.get("text"))
                    if sentence.get("sentence_end") is True:
                        if text and (not final_sentences or final_sentences[-1] != text):
                            final_sentences.append(text)
                        partial_text = ""
                    elif text:
                        partial_text = text
                elif event_name == "task-finished":
                    break
                elif event_name == "task-failed":
                    raise RuntimeError(header.get("error_message") or header.get("error_code") or "DashScope ASR failed")

        text = " ".join(part for part in final_sentences if part).strip()
        if not text:
            text = partial_text.strip()
        return text

    async def _await_task_started(self, websocket: Any, task_id: str) -> None:
        while True:
            message = await asyncio.wait_for(websocket.recv(), timeout=10)
            if isinstance(message, bytes):
                continue
            event = json.loads(message)
            header = event.get("header") or {}
            event_name = header.get("event", "")
            if header.get("task_id") != task_id:
                continue
            if event_name == "task-started":
                return
            if event_name == "task-failed":
                raise RuntimeError(header.get("error_message") or header.get("error_code") or "DashScope ASR failed")


class FunAsrLocalClient(BaseAsrClient):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None
        self._lock = asyncio.Lock()

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "",
        content_type: str = "",
        audio_format: str = "",
        sample_rate: int | None = None,
        channels: int | None = None,
        audio_path: str = "",
    ) -> TranscriptionResult:
        temp_path = ""
        path = audio_path
        if not path:
            suffix = Path(filename or "audio.wav").suffix or ".wav"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(audio)
                temp_path = temp_file.name
                path = temp_path

        try:
            async with self._lock:
                text = await asyncio.to_thread(self._transcribe_path, path)
        except ImportError as exc:
            return TranscriptionResult(
                ok=False,
                provider=self.settings.asr_provider,
                error=f"FunASR local dependencies are not installed: {exc}",
            )
        except Exception as exc:
            return TranscriptionResult(
                ok=False,
                provider=self.settings.asr_provider,
                error=str(exc) or exc.__class__.__name__,
            )
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)

        return TranscriptionResult(
            ok=bool(text),
            provider=self.settings.asr_provider,
            text=text,
            error=None if text else "FunASR completed without recognized text.",
        )

    def _transcribe_path(self, audio_path: str) -> str:
        model = self._load_model()
        if is_sensevoice_model(self.settings.asr_local_model):
            result = model.generate(
                input=audio_path,
                cache={},
                language="auto",
                use_itn=True,
                batch_size_s=max(1, min(self.settings.asr_batch_size_s, 60)),
                merge_vad=self.settings.asr_merge_vad,
                merge_length_s=self.settings.asr_merge_length_s,
            )
        else:
            kwargs: dict[str, Any] = {
                "input": audio_path,
                "batch_size_s": self.settings.asr_batch_size_s,
            }
            if self.settings.asr_hotword:
                kwargs["hotword"] = self.settings.asr_hotword
            result = model.generate(**kwargs)
        return extract_funasr_text(result)

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        from funasr import AutoModel

        kwargs: dict[str, Any] = {
            "model": self.settings.asr_local_model,
            "device": self.settings.asr_local_device,
            "disable_update": True,
        }
        if self.settings.asr_local_vad_model:
            kwargs["vad_model"] = self.settings.asr_local_vad_model
            if self.settings.asr_vad_max_segment_ms > 0:
                kwargs["vad_kwargs"] = {"max_single_segment_time": self.settings.asr_vad_max_segment_ms}
        if self.settings.asr_local_punc_model and not is_sensevoice_model(self.settings.asr_local_model):
            kwargs["punc_model"] = self.settings.asr_local_punc_model

        self._model = AutoModel(**kwargs)
        return self._model


def get_asr_client(settings: Settings) -> BaseAsrClient:
    provider = settings.asr_provider.lower()
    if provider in {"funasr_local", "sensevoice_local"}:
        return FunAsrLocalClient(settings)
    if provider == "dashscope_paraformer" and settings.dashscope_api_key:
        return DashScopeParaformerClient(settings)
    return UnavailableAsrClient(settings)


def build_audio_meta(
    audio: bytes,
    *,
    filename: str = "",
    content_type: str = "",
    audio_format: str = "",
    sample_rate: int | None = None,
    channels: int | None = None,
) -> AudioMeta:
    fmt = detect_audio_format(audio, filename=filename, content_type=content_type, explicit_format=audio_format)
    actual_sample_rate = sample_rate
    actual_channels = channels
    content = audio
    if fmt == "wav":
        parsed_sample_rate, parsed_channels, parsed_content = parse_wav_audio(audio)
        actual_sample_rate = actual_sample_rate or parsed_sample_rate
        actual_channels = actual_channels or parsed_channels
        content = parsed_content
        fmt = "pcm"
    elif fmt == "pcm":
        actual_sample_rate = actual_sample_rate or 16000
        actual_channels = actual_channels or 1
    else:
        actual_sample_rate = actual_sample_rate or 16000

    if not actual_sample_rate or actual_sample_rate <= 0:
        raise ValueError("sample_rate must be provided for this audio format")
    if actual_channels is not None and actual_channels != 1:
        raise ValueError("only mono audio is supported for the ESP32S3 ASR path")

    return AudioMeta(
        content=content,
        format=fmt,
        sample_rate=actual_sample_rate,
        channels=actual_channels,
    )


def detect_audio_format(audio: bytes, *, filename: str = "", content_type: str = "", explicit_format: str = "") -> str:
    normalized = normalize_audio_format(explicit_format)
    if normalized:
        return normalized
    if audio.startswith(b"RIFF") and b"WAVE" in audio[:16]:
        return "wav"

    suffix = ""
    if "." in filename:
        suffix = filename.rsplit(".", 1)[-1].lower()
    normalized = normalize_audio_format(suffix)
    if normalized:
        return normalized

    content_type = content_type.lower().strip()
    mime_map = {
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/wave": "wav",
        "audio/pcm": "pcm",
        "audio/l16": "pcm",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/aac": "aac",
        "audio/amr": "amr",
        "audio/ogg": "opus",
    }
    if content_type in mime_map:
        return mime_map[content_type]

    raise ValueError("unable to infer audio format; provide audio_format=wav or audio_format=pcm")


def normalize_audio_format(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "raw":
        normalized = "pcm"
    return normalized if normalized in SUPPORTED_AUDIO_FORMATS else ""


def parse_wav_audio(audio: bytes) -> tuple[int, int, bytes]:
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            frames = wav_file.readframes(wav_file.getnframes())
            return sample_rate, channels, frames
    except (wave.Error, EOFError) as exc:
        raise ValueError("uploaded WAV file is invalid or incomplete") from exc


def chunk_audio(audio: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[bytes]:
    return [audio[index : index + chunk_size] for index in range(0, len(audio), chunk_size)]


def normalize_transcript(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_sensevoice_model(model_name: str) -> bool:
    return "sensevoice" in model_name.lower()


def strip_rich_transcription_tags(value: Any) -> str:
    text = re.sub(r"<\|[^>]+?\|>", "", str(value or ""))
    return normalize_transcript(text)


def extract_funasr_text(result: Any) -> str:
    if isinstance(result, str):
        return strip_rich_transcription_tags(result)
    if isinstance(result, list):
        return normalize_transcript(" ".join(extract_funasr_text(item) for item in result))
    if isinstance(result, dict):
        if "text" in result:
            return strip_rich_transcription_tags(result.get("text"))
        sentence_info = result.get("sentence_info")
        if isinstance(sentence_info, list):
            return normalize_transcript(
                " ".join(strip_rich_transcription_tags(item.get("text", "")) for item in sentence_info if isinstance(item, dict))
            )
    return strip_rich_transcription_tags(result)
