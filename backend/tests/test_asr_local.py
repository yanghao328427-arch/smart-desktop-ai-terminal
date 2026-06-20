import asyncio
import sys
from types import SimpleNamespace

from app.asr import FunAsrLocalClient, extract_funasr_text, get_asr_client, strip_rich_transcription_tags
from app.config import Settings


def test_funasr_text_extraction_strips_rich_tags():
    result = [{"text": "<|zh|><|NEUTRAL|><|Speech|><|woitn|>open the fan"}]

    assert extract_funasr_text(result) == "open the fan"
    assert strip_rich_transcription_tags("<|en|>hello   world") == "hello world"


def test_get_asr_client_selects_local_funasr_provider():
    client = get_asr_client(Settings(asr_provider="funasr_local"))

    assert isinstance(client, FunAsrLocalClient)


def test_funasr_local_client_uses_audio_path_and_model_settings(monkeypatch, tmp_path):
    model_calls = []
    generate_calls = []

    class FakeModel:
        def generate(self, **kwargs):
            generate_calls.append(kwargs)
            return [{"text": "<|zh|><|Speech|>turn on the lamp"}]

    def fake_auto_model(**kwargs):
        model_calls.append(kwargs)
        return FakeModel()

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=fake_auto_model))
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake wav")
    client = FunAsrLocalClient(
        Settings(
            asr_provider="funasr_local",
            asr_local_model="paraformer-zh",
            asr_local_vad_model="fsmn-vad",
            asr_local_punc_model="ct-punc",
            asr_local_device="cpu",
            asr_hotword="lamp fan",
        )
    )

    result = asyncio.run(client.transcribe(b"ignored", filename="sample.wav", audio_path=str(audio_path)))

    assert result.ok is True
    assert result.provider == "funasr_local"
    assert result.text == "turn on the lamp"
    assert model_calls[0]["model"] == "paraformer-zh"
    assert model_calls[0]["vad_model"] == "fsmn-vad"
    assert model_calls[0]["punc_model"] == "ct-punc"
    assert generate_calls[0]["input"] == str(audio_path)
    assert generate_calls[0]["hotword"] == "lamp fan"


def test_sensevoice_local_client_uses_merge_vad(monkeypatch, tmp_path):
    generate_calls = []

    class FakeModel:
        def generate(self, **kwargs):
            generate_calls.append(kwargs)
            return [{"text": "<|zh|><|Speech|>long sentence recognized"}]

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=lambda **kwargs: FakeModel()))
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake wav")
    client = FunAsrLocalClient(
        Settings(
            asr_provider="funasr_local",
            asr_local_model="iic/SenseVoiceSmall",
            asr_batch_size_s=300,
            asr_merge_vad=True,
            asr_merge_length_s=15,
        )
    )

    result = asyncio.run(client.transcribe(b"ignored", audio_path=str(audio_path)))

    assert result.ok is True
    assert result.text == "long sentence recognized"
    assert generate_calls[0]["language"] == "auto"
    assert generate_calls[0]["use_itn"] is True
    assert generate_calls[0]["batch_size_s"] == 60
    assert generate_calls[0]["merge_vad"] is True
