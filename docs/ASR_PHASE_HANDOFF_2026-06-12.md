# ASR 阶段性交接：ESP32S3 麦克风与高精度识别模型

更新时间：2026-06-12 +08:00

## 下一窗口第一句话

请先读取 `docs/ASR_PHASE_HANDOFF_2026-06-12.md`、`docs/LOCAL_ASR_FUNASR.md`、`docs/ESP32_MIC_ASR_PHASE_PLAN.md`、`docs/NEXT_WINDOW_HANDOFF.md`、`docs/CURRENT_PROGRESS_HANDOFF.md`。当前目标是在保留浏览器语音兜底和不泄露 `backend/.env` 的前提下，继续解决 ESP32S3 板载麦克风短录音上传到后端 ASR 的识别准确率问题，优先完成本地高精度 FunASR/Paraformer 或 SenseVoice 模型的可用性验证，再做长句人声测试。

## 当前结论

短录音上传链路已经打通，硬件麦克风能采到有效音频；短词 `风扇` 自循环测试曾识别成功，说明 ESP32S3 录音、HTTP 上传、后端 ASR、状态回传链路是通的。但更长短句如 `关闭风扇` 出现过只识别成 `风扇。` 的情况，说明当前录音时机、TTS 播放回录质量、模型选择和长句准确率还需要继续调优。

现阶段不要把浏览器 Web Speech 入口删除或替换。它仍然是答辩和演示的兜底链路：

```text
浏览器语音 -> /api/asr/recognized -> 后端 AI/Qwen -> ESP32S3 -> STM32/SYN6288/OLED/执行器 -> ACK
```

新增硬件麦克风链路是增强链路：

```text
ESP32S3 板载 PDM 麦克风 -> 3 秒 WAV/PCM -> POST /api/asr/transcribe
-> 后端 ASR -> 可选 inject 到 /api/chat -> Qwen/动作链路 -> STM32 ACK
```

## 已完成代码与配置

- `backend/app/asr.py`：已新增可选本地 `FunAsrLocalClient`，支持 provider `funasr_local` / `sensevoice_local`。
- `backend/app/asr.py`：DashScope WAV 上传已改为解析 WAV 并提取 PCM 帧，避免把 WAV 头直接发给 realtime ASR 导致空文本。
- `backend/app/asr.py`：新增 FunASR/SenseVoice 输出文本提取和富标签清理，例如清理 `<|zh|><|Speech|>`。
- `backend/app/config.py`：新增本地 ASR 配置项：`ASR_LOCAL_MODEL`、`ASR_LOCAL_VAD_MODEL`、`ASR_LOCAL_PUNC_MODEL`、`ASR_LOCAL_DEVICE`、`ASR_HOTWORD`、`ASR_VAD_MAX_SEGMENT_MS`、`ASR_BATCH_SIZE_S`、`ASR_MERGE_VAD`、`ASR_MERGE_LENGTH_S`。
- `backend/app/main.py`：`/api/asr/transcribe` 已把保存后的 `audio_path` 传给 ASR 客户端，本地大模型可以直接读取 WAV 文件。
- `backend/requirements-asr-local.txt`：新增本地 ASR 可选依赖，不污染主后端依赖。
- `backend/.venv-asr`：已用 Python 3.12 创建独立 ASR 虚拟环境，并安装基础后端依赖、PyTorch CPU、torchaudio、funasr、modelscope、soundfile。
- `tools/start_backend_funasr.ps1`：新增本地 FunASR 后端启动脚本，通过进程环境变量启用 `funasr_local`，不读取、不打印、不改写 `backend/.env`。
- `.gitignore`：已忽略 `.venv-asr/` 和 `backend/.venv-asr/`，避免误提交大依赖环境。
- `docs/LOCAL_ASR_FUNASR.md`：已记录模型选择、安装顺序、启动配置和验证建议。

## 已完成硬件与自测

- ESP32S3 固件已支持 XIAO ESP32S3 Sense 板载 PDM 麦克风。
- 当前麦克风参数：16 kHz、mono、16-bit PCM，封装 WAV 上传。
- 当前录音窗口：3 秒。
- ESP32S3 已实现 `CFG:MIC:REC`：录音并上传，`inject=true`。
- ESP32S3 已实现 `CFG:MIC:SELFTEST:<短句>`：先通过 STM32/SYN6288 播放短句，再录音上传，`inject=false`，并把识别结果写入 telemetry。
- `tools/mic_selftest.py` 已可从电脑侧打开 COM8 触发自循环测试，并轮询后端状态。
- 2 秒测试时曾记录到有效音频：16 kHz mono，RMS 约 5828，peak 约 21040，说明麦克风不是静音。
- 短词 `风扇` 自循环测试曾通过，识别为 `风扇。`。
- `关闭风扇` 自循环测试曾出现只识别为 `风扇。`，说明开头音节容易丢失。

## 已验证命令

后端测试在当前 Espressif Python 环境通过：

```powershell
python -m pytest backend/tests/test_asr_local.py backend/tests/test_phase1.py -q
```

结果：

```text
29 passed, 1 warning
```

后端测试在独立 ASR 虚拟环境也通过：

```powershell
backend\.venv-asr\Scripts\python.exe -m pytest backend/tests/test_asr_local.py backend/tests/test_phase1.py -q
```

结果：

```text
29 passed, 1 warning
```

FunASR 可导入：

```powershell
@'
from funasr import AutoModel
print('FUNASR_IMPORT_OK')
'@ | backend\.venv-asr\Scripts\python.exe -
```

结果：

```text
FUNASR_IMPORT_OK
```

备注：导入时提示未安装 ffmpeg，但 WAV 上传可以回退到 torchaudio，不是当前阻塞点。

## 当前阻塞点

完整预加载 `paraformer-zh + fsmn-vad + ct-punc` 曾运行 20 分钟未返回，疑似 ModelScope 模型下载或初始化在当前网络下过慢。命令超时后已停止，不应视为模型预下载完成。

当前后端不要直接强切到本地模型长期运行，否则首次识别可能卡在模型下载/初始化。建议下一窗口先单独解决模型缓存下载或换用更小模型验证。

## 推荐模型路线

首选：

```text
ASR_PROVIDER=funasr_local
ASR_LOCAL_MODEL=paraformer-zh
ASR_LOCAL_VAD_MODEL=fsmn-vad
ASR_LOCAL_PUNC_MODEL=ct-punc
ASR_LOCAL_DEVICE=cpu
ASR_VAD_MAX_SEGMENT_MS=60000
ASR_BATCH_SIZE_S=300
```

原因：中文普通话长句识别优先，配合 VAD 和标点更适合人类自然语音。

备选：

```text
ASR_PROVIDER=funasr_local
ASR_LOCAL_MODEL=iic/SenseVoiceSmall
ASR_LOCAL_VAD_MODEL=fsmn-vad
ASR_LOCAL_PUNC_MODEL=
ASR_LOCAL_DEVICE=cpu
ASR_BATCH_SIZE_S=60
ASR_MERGE_VAD=true
ASR_MERGE_LENGTH_S=15
```

原因：SenseVoiceSmall 对复杂声音、噪声、多语种场景可能更稳，也可能比大 Paraformer 更容易先跑起来。

暂不推荐优先用 `sherpa-onnx` 作为本项目长句主识别模型。它适合轻量离线部署，但当前目标是后端电脑高准确率中文长句识别，FunASR/Paraformer 或 SenseVoice 更贴合。

参考：

- FunASR: https://github.com/modelscope/FunASR
- SenseVoice: https://github.com/FunAudioLLM/SenseVoice
- sherpa-onnx: https://github.com/k2-fsa/sherpa-onnx
- FunASR tutorial: https://modelscope.github.io/FunASR/tutorial.html

## 下一窗口建议步骤

1. 不读取、不打印、不提交 `backend/.env`。
2. 确认当前后端如果在运行，先不要替换成 `funasr_local`，除非已经解决模型下载和冷启动耗时。
3. 用 `backend\.venv-asr\Scripts\python.exe` 单独测试模型下载和初始化，优先尝试 `iic/SenseVoiceSmall` 或指定 ModelScope 缓存。
4. 如果模型初始化成功，再用 `tools/start_backend_funasr.ps1` 启动本地 ASR 后端。
5. 先上传已有 `backend/data/audio/` 里的 ESP32S3 WAV 文件做识别，不急着让硬件重新录。
6. 如果本地 ASR 能识别已有文件，再运行 `python tools/mic_selftest.py --port COM8 --base-url http://127.0.0.1:8083 --phrase 风扇 --timeout 100`。
7. 短词稳定后，测试 3 秒以内短句，例如 `打开风扇`、`关闭风扇`、`现在温度多少`。
8. 短句稳定后，再测试真人长句，不再依赖 SYN6288 自循环，因为 TTS 播放回录不能完全代表人声。

## 可能的准确率调优方向

- 录音开始前给 SYN6288/TTS 留 100 到 300 ms 缓冲，避免开头字被截掉。
- 录音窗口从固定 3 秒改为 VAD 或前后各留静音边界，避免只录到后半句。
- 对 PCM 做更温和的增益，防止开头爆音或削波影响识别。
- 增加热词：`风扇`、`桌面终端`、`温度`、`湿度`、`学习模式`、`专注模式`。
- 测试真实人声 WAV，而不是只用 SYN6288 自循环；自循环适合无人值守烟测，但不是最终准确率标准。
- 如果 CPU 版延迟太高，后续再考虑 CUDA 版 PyTorch 或云端高精度非实时 ASR。

## 安全边界

- `backend/.env` 存在，但不要读取、打印、复制、提交或无必要修改。
- 文档中只记录 provider、model、状态和命令，不记录 API Key。
- 浏览器语音兜底必须保留。
- 本地 ASR 虚拟环境和模型缓存不要提交。
- 当前仓库整体仍像是未跟踪状态，提交前要非常小心筛选文件。
