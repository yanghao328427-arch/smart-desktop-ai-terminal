# AI 与 ASR 选型决策

更新时间：2026-06-10

## 最终选型

| 能力 | 选型 | 原因 |
| --- | --- | --- |
| LLM 对话 | 阿里云百炼 Qwen，默认 `qwen-plus` | 国内网络更稳，中文效果好，支持 OpenAI 兼容接口 |
| ASR 语音识别 | 阿里云百炼 Paraformer | 中文语音识别链路成熟，官方支持实时 WebSocket |
| TTS 播报 | 本地 SYN6288 | 硬件已经具备，课程展示实物闭环更强 |
| 唤醒 | ESP32S3 本地唤醒 | 不把唤醒依赖放到云端，降低延迟与网络风险 |

## 官方接口依据

- 百炼 OpenAI 兼容接口：`https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope`
- 百炼文本生成模型 API：`https://help.aliyun.com/zh/model-studio/qwen-api-reference/`
- Paraformer 实时语音识别 WebSocket：`https://help.aliyun.com/zh/model-studio/websocket-for-paraformer-real-time-service`

## 后端环境变量

不要把 API Key 写入固件、Markdown、前端或小程序。

```ini
AI_PROVIDER=dashscope_openai
AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_MODEL=qwen-plus
DASHSCOPE_API_KEY=<local-only>
ASR_PROVIDER=dashscope_paraformer
ASR_WS_URL=wss://dashscope.aliyuncs.com/api-ws/v1/inference
```

## 实现路线

### 阶段 1：文本闭环

Web/小程序输入文字：

```text
用户文本 -> FastAPI -> Qwen -> 工具动作 -> ESP32S3 -> STM32 -> SYN6288/OLED/执行器
```

阶段目标：

- 不依赖麦克风和 ASR。
- 先证明 AI 能生成正确回复和硬件动作。
- 避免把旧项目最大不确定性一次性带回来。

### 阶段 2：短句录音 ASR

ESP32S3 上传一段固定长度音频：

```text
ESP32S3 录音 -> FastAPI 保存 WAV -> Paraformer/ASR -> 文本闭环
```

阶段目标：

- 保存原始音频，方便人工回放。
- 明确区分“没录到”“录到了但识别失败”“识别成功但下发失败”。

当前阶段性计划详见：

```text
docs/ESP32_MIC_ASR_PHASE_PLAN.md
```

执行原则：

- 保留浏览器 Web Speech API 作为答辩兜底入口。
- ESP32S3 麦克风先做 3 秒短录音上传，不直接上实时流式。
- 真实识别成功后复用现有 Qwen/STM32 ACK 主链路。

### 阶段 3：实时 ASR

稳定后再升级为流式：

```text
ESP32S3 WebSocket 音频帧 -> FastAPI -> Paraformer WebSocket -> 增量识别 -> 对话闭环
```

阶段目标：

- 降低响应延迟。
- 支持更自然的连续对话。

## 备用方案

OpenAI 语音识别和 Realtime API 保留为备用路线，但不是本项目首选。原因：

- 国内网络链路不如百炼稳定。
- 实时语音 Agent 架构复杂度更高。
- 课程设计更看重可演示、可解释、可复现。
