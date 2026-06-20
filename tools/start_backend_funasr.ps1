param(
    [ValidateSet("paraformer", "sensevoice")]
    [string]$Profile = "paraformer"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot "backend\.venv-asr\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Missing backend\.venv-asr. Create it with: py -3.12 -m venv backend/.venv-asr"
}

$env:ASR_PROVIDER = "funasr_local"
$env:ASR_LOCAL_DEVICE = "cpu"
$env:ASR_HOTWORD = ""

if ($Profile -eq "sensevoice") {
    $env:ASR_LOCAL_MODEL = "iic/SenseVoiceSmall"
    $env:ASR_LOCAL_VAD_MODEL = "fsmn-vad"
    $env:ASR_LOCAL_PUNC_MODEL = ""
    $env:ASR_VAD_MAX_SEGMENT_MS = "60000"
    $env:ASR_BATCH_SIZE_S = "60"
    $env:ASR_MERGE_VAD = "true"
    $env:ASR_MERGE_LENGTH_S = "15"
} else {
    $env:ASR_LOCAL_MODEL = "paraformer-zh"
    $env:ASR_LOCAL_VAD_MODEL = "fsmn-vad"
    $env:ASR_LOCAL_PUNC_MODEL = "iic/punc_ct-transformer_cn-en-common-vocab471067-large"
    $env:ASR_VAD_MAX_SEGMENT_MS = "60000"
    $env:ASR_BATCH_SIZE_S = "300"
}

Set-Location $repoRoot
& $python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8083
