# 云端真实对话交接

更新时间：2026-06-11 21:56 +08:00

## 一句话状态

智能桌面对话终端已经完成真实 DashScope Qwen-Plus 云端对话闭环：浏览器/小程序/脚本输入进入后端，后端携带实时传感器状态和多轮上下文调用云端模型，生成回复后下发 STM32/SYN6288 播报与 OLED 动作，并收到 STM32 ACK。

## 本轮完成

- 后端 `/api/health` 已能安全返回 `ai_provider`、`ai_model`、`cloud_ready`，不返回任何 API Key。
- 本机后端配置已能被 `Settings()` 识别为 `cloud_ready=true`；真实 Key 仍只在本机 `backend/.env`，不要打印、提交或复制到文档。
- 云端 Qwen 现在被要求输出结构化 `{"reply","speech"}`：`reply` 给 Web/小程序保留完整文本，`speech` 给 SYN6288 播报更短短句。
- 新增 `tools/cloud_dialogue_smoke.py`，用于三轮多轮对话冒烟测试。
- 冒烟脚本会检测 `cloud_fallback_detected`，避免把“云端失败后本地规则兜底”误判成真实云端对话。
- 冒烟脚本现在逐轮等待 STM32 ACK，避免连续三轮对话过快堆积串口动作。
- Web 控制台和小程序状态页现在会显示最近播报短句，便于现场说明“完整回复”和“喇叭播报”是分离的工程设计。
- TTSHEX 播报 payload 已按 UTF-8 字节截断到 120 字节，降低云端长回复导致 SYN6288/STM32 ACK ERR 的风险。

## 已验证结果

后端健康检查：

```json
{
  "status": "ok",
  "ai_provider": "dashscope_openai",
  "ai_model": "qwen-plus",
  "cloud_ready": true
}
```

强制云端冒烟命令：

```powershell
python tools\cloud_dialogue_smoke.py --base-url http://127.0.0.1:8083 --require-cloud --ack-wait-seconds 20
```

最近一次通过结果：

```text
cloud_ready=true
cloud_fallback_detected=false
ai_provider=dashscope_openai
ai_model=qwen-plus
device_online=true
uart_ok=true
session_connected=true
sensor_keys=aht20_ok,distance_ok,humidity_pct,pot_raw,temperature_c,uptime_ms
ack_ok_count=6
ack_err_count=0
pending_action_count=0
```

自动化测试：

```powershell
python -m pytest backend\tests -q
```

结果：

```text
23 passed, 1 warning
```

## 现场复测顺序

1. 启动后端：

```powershell
python tools\start_backend.py --bind-host 0.0.0.0 --health-host 127.0.0.1 --port 8083 --timeout 20
```

2. 检查云端模式：

```powershell
Invoke-RestMethod http://127.0.0.1:8083/api/health | ConvertTo-Json
```

3. 强制云端多轮对话验收：

```powershell
python tools\cloud_dialogue_smoke.py --base-url http://127.0.0.1:8083 --require-cloud --ack-wait-seconds 20
```

4. 浏览器真实语音演示：

```text
Chrome / Edge 打开 http://127.0.0.1:8083/console
点击“开始语音”
说：现在状态怎么样
观察：识别文本 -> Qwen 回复 -> SYN6288 播报 -> STM32 ACK
```

## 当前注意事项

- 不要泄露、打印或提交 `backend/.env`；文档里只允许写 `cloud_ready=true/false` 这类状态。
- 如果 `/api/health` 显示 `cloud_ready=false`，说明后端没有进入真实云端模型模式，不能在答辩中宣称已经走云端 Qwen。
- 如果脚本显示 `cloud_fallback_detected=true`，说明请求过程中云端失败并回退本地规则，需要先排查网络、Key 权限或 DashScope 服务状态。
- 超声波当前仍是 `distance_ok=false`，但温湿度、电位器和距离状态字段都已进入后端，答辩时可说明距离传感器链路已接入、当前实测无有效距离值。
- 真实云端模型回复会更自然、更长，当前已拆成完整 `reply` 和更短 `speech`；SYN6288 优先播报 `speech`，后端仍保留截断兜底，Web/小程序继续显示完整回复。

## 下一步建议

- 答辩前固定演示三句话：“你是谁”“现在状态怎么样”“你记得我刚才问了什么吗，给我一个学习建议”。
- 语音入口优先用 Web 控制台的浏览器语音识别，ESP32S3 继续负责联网、RFID、UART 桥接和 ACK 回传。
- 如果现场觉得播报仍偏长，再微调 `backend/app/ai.py` 里的云端 prompt 和 `SPEECH_MAX_BYTES`。
