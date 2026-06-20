# 本地密钥与配置

本项目会用到 Wi-Fi 密码和云端 API Key。这些内容只允许放在本地未提交文件中。

## 禁止写入的位置

- Markdown 文档。
- Git 提交历史。
- ESP32S3 固件源码。
- STM32 固件源码。
- 小程序前端源码。
- 浏览器可见的 JS 文件。

## 后端 `.env`

建议文件：`backend/.env`

```ini
AI_PROVIDER=dashscope_openai
AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_MODEL=qwen-plus
DASHSCOPE_API_KEY=<your_dashscope_api_key>

ASR_PROVIDER=dashscope_paraformer
ASR_WS_URL=wss://dashscope.aliyuncs.com/api-ws/v1/inference

WIFI_SSID=Tenda_2C7AD0
WIFI_PASSWORD=<your_wifi_password>

DEVICE_ID=desktop-agent-001
EDGE_ID=esp32s3-sense-001
```

## ESP32S3 配置策略

第一阶段允许通过 USB 串口配置 Wi-Fi：

```text
CFG:WIFI:Tenda_2C7AD0,<password>
CFG:SERVER:http://<backend-lan-ip>:8083
CFG:WIFI:SHOW
CFG:WIFI:SCAN
```

长期策略：

- ESP32S3 用 NVS/Preferences 保存 Wi-Fi 与服务器地址。
- 后端 API Key 绝不下发给 ESP32S3。
- ASR 和 LLM 都由后端代调用。

## 密钥检查

提交前运行：

```powershell
git status --short
git diff
```

检查是否误写：

- Wi-Fi 密码。
- DashScope API Key。
- OpenAI 或其他模型平台 Key。
- 手机号、邮箱等私人信息。
