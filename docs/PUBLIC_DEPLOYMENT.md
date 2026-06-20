# 公网部署说明

目标：网页端和小程序端访问同一个公网后端，状态、传感器、RFID、ASR、AI 对话继续来自真实 FastAPI + ESP32/STM32 链路，不使用截图或演示假数据。

## 当前公网地址

- Hugging Face Space: https://huggingface.co/spaces/yh001399/smart-desktop-ai-terminal
- Web API / App: https://yh001399-smart-desktop-ai-terminal.hf.space
- 网页控制台: https://yh001399-smart-desktop-ai-terminal.hf.space/console
- 健康检查: https://yh001399-smart-desktop-ai-terminal.hf.space/api/health

GitHub 仓库已公开，Hugging Face Dockerfile 会从公开仓库拉取当前工程构建。

## Hugging Face 环境变量

已设置：

- `CONTROL_TOKEN`: Secret，用于保护控制、AI 对话、RFID 写入、ASR 上传等写操作。
- `AI_PROVIDER=dashscope_openai`
- `AI_MODEL=qwen-plus`
- `ASR_PROVIDER=dashscope_paraformer`

仍需你在 Hugging Face Space Settings -> Variables and secrets 里手动新增 Secret：

- `DASHSCOPE_API_KEY`: 通义千问 / DashScope ASR 使用的 API Key。

不把 `backend/.env` 上传到公网，也不要把密钥写入代码或文档。

## 网页端使用

打开：

```text
https://yh001399-smart-desktop-ai-terminal.hf.space/console
```

在左侧“控制口令”输入同一个 `CONTROL_TOKEN`。状态读取、诊断、传感器面板是公开实时读接口；控制、AI 对话、RFID、ASR 上传等写操作会携带 `X-Demo-Token`。

## 小程序端使用

小程序默认后端已指向：

```text
https://yh001399-smart-desktop-ai-terminal.hf.space
```

使用步骤：

1. 在小程序首页保存“公网控制口令”，值为 Hugging Face 的 `CONTROL_TOKEN`。
2. 微信公众平台后台需要把下面域名加入 request 合法域名：

```text
https://yh001399-smart-desktop-ai-terminal.hf.space
```

3. 重新预览或上传小程序版本。

## ESP32 接入公网后端

公网 Hugging Face Space 使用 HTTPS/WSS。ESP32 固件已支持 `https://` / `wss://` 服务地址。刷入固件后，用串口配置实际公网后端：

```powershell
python tools/configure_esp32.py --port COM8 --server https://yh001399-smart-desktop-ai-terminal.hf.space
```

配置后，ESP32 的心跳、遥测、WebSocket 闭环状态会回传到公网后端，网页端和小程序端才能看到真实实时数据。

## 注意事项

- Hugging Face 免费 Space 会休眠，第一次打开可能需要等待冷启动。
- 免费环境文件系统不是长期持久存储，RFID 注册表和上传音频重启后可能丢失；长期演示可以接数据库或持久存储。
- 设备侧上报接口目前保留无口令，以兼容现有 ESP32/STM32 实时链路；控制类接口已用 `CONTROL_TOKEN` 保护。
- `DASHSCOPE_API_KEY` 没设置前，`/api/health` 会显示 `cloud_ready=false`，AI/ASR 会降级；这不是假数据，而是明确的未配置状态。
