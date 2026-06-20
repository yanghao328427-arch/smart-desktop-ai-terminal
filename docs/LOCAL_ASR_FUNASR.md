# Local high-accuracy ASR

This backend can keep the existing DashScope realtime ASR and browser speech fallback, while adding an optional local
FunASR provider for longer human speech.

## Recommended models

- `paraformer-zh` with `fsmn-vad` and `ct-punc`: best default for Mandarin long-sentence recognition on the backend PC.
- `iic/SenseVoiceSmall`: useful when the input may include multilingual speech, emotion/noise tags, or less controlled audio.
- `sherpa-onnx`: good for embedded/offline lightweight deployments, but not the first choice here when long Chinese accuracy matters.

The ESP32S3 should still only capture and upload short WAV/PCM audio. The heavy model runs on the backend computer.

## Install in a separate Python environment

Do not install these packages into the Espressif Python 3.13 environment. Use a separate Python 3.10, 3.11, or 3.12
environment with a compatible PyTorch build.

```powershell
cd backend
python -m venv .venv-asr
.\.venv-asr\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-asr-local.txt
```

For NVIDIA GPU acceleration, install the PyTorch build that matches the CUDA version first, then install the remaining
requirements.

If `pip install -r requirements-asr-local.txt` spends a long time resolving dependencies, install PyTorch first with the
command above, then run:

```powershell
python -m pip install funasr modelscope soundfile
```

`ffmpeg` is optional for WAV uploads; FunASR can fall back to `torchaudio` for audio loading.

## Download models with validation

If ModelScope downloads stall through the local proxy, use the dedicated downloader from the ASR environment. It removes
proxy variables for that process only, downloads the full snapshot, and validates every file by size and SHA256.

```powershell
backend\.venv-asr\Scripts\python.exe -u tools\download_modelscope_snapshot.py iic/SenseVoiceSmall --clean --no-proxy --sha256
backend\.venv-asr\Scripts\python.exe -u tools\download_modelscope_snapshot.py iic/speech_fsmn_vad_zh-cn-16k-common-pytorch --clean --no-proxy --sha256
```

Expected SenseVoiceSmall `model.pt` size:

```text
936291369 bytes
```

For the Paraformer profile:

```powershell
backend\.venv-asr\Scripts\python.exe -u tools\download_modelscope_snapshot.py iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch --clean --no-proxy --sha256
backend\.venv-asr\Scripts\python.exe -u tools\download_modelscope_snapshot.py iic/punc_ct-transformer_cn-en-common-vocab471067-large --clean --no-proxy --sha256
```

`ct-punc` resolves to `iic/punc_ct-transformer_cn-en-common-vocab471067-large` in the current FunASR package, so the
startup script pins that exact model id.

## Backend settings

Set these in the backend environment file or process environment. Do not print or commit secrets.

```dotenv
ASR_PROVIDER=funasr_local
ASR_LOCAL_MODEL=paraformer-zh
ASR_LOCAL_VAD_MODEL=fsmn-vad
ASR_LOCAL_PUNC_MODEL=ct-punc
ASR_LOCAL_DEVICE=cpu
ASR_VAD_MAX_SEGMENT_MS=60000
ASR_BATCH_SIZE_S=300
ASR_HOTWORD=风扇 桌面终端 小爱 同学
```

For SenseVoice:

```dotenv
ASR_PROVIDER=funasr_local
ASR_LOCAL_MODEL=iic/SenseVoiceSmall
ASR_LOCAL_VAD_MODEL=fsmn-vad
ASR_LOCAL_PUNC_MODEL=
ASR_LOCAL_DEVICE=cpu
ASR_BATCH_SIZE_S=60
ASR_MERGE_VAD=true
ASR_MERGE_LENGTH_S=15
```

To start the backend with the validated SenseVoice profile without touching `backend/.env`:

```powershell
.\tools\start_backend_funasr.ps1 -Profile sensevoice
```

## Verification

After starting the backend from the ASR environment, use the ESP32S3 self-loop test first:

```powershell
python tools/mic_selftest.py --port COM8 --base-url http://127.0.0.1:8083 --phrase 风扇 --timeout 100
```

Then test longer human-like sentences by uploading recorded WAV files to `/api/asr/transcribe`. Browser speech fallback
still uses `/api/asr/recognized` and does not depend on the local model.

## References

- FunASR: https://github.com/modelscope/FunASR
- SenseVoice: https://github.com/FunAudioLLM/SenseVoice
- sherpa-onnx: https://github.com/k2-fsa/sherpa-onnx
- FunASR tutorial: https://modelscope.github.io/FunASR/tutorial.html
