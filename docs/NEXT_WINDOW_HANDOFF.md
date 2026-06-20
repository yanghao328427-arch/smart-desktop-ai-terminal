# 下一窗口交接总结

更新时间：2026-06-11 22:25 +08:00

## 开局第一句话

请先读取 `docs/NEXT_WINDOW_HANDOFF.md`、`docs/CURRENT_PROGRESS_HANDOFF.md`、`docs/ESP32_MIC_ASR_PHASE_PLAN.md`、`docs/AI_ASR_DECISION.md`、`docs/CLOUD_DIALOGUE_HANDOFF.md`、`docs/PROTOCOL.md`、`docs/HARDWARE_WIRING.md`。当前项目重点是课程答辩可落地的“智能桌面对话终端”：真实语音/文本输入进入后端，后端调用云端 Qwen-Plus，结合传感器和多轮上下文生成回复，再下发 STM32/SYN6288 播报与 OLED/风扇等动作，并收到 STM32 ACK。下一阶段是在保留浏览器语音兜底的同时，推进 ESP32S3 Sense 板载麦克风短录音上传与真实 Paraformer ASR。不要打印、提交、泄露或无必要改动 `backend/.env`。

## 当前一句话状态

真实云端智能对话链路已经跑通：`cloud_ready=true`、`cloud_fallback_detected=false`，并完成 Qwen-Plus 多轮回复到 STM32/SYN6288/OLED 的 ACK 闭环。

## 已验证关键结果

- STM32 已支持 `NET:TTS` / `NET:TTSHEX` 到 SYN6288，用户已听到实际播报。
- ESP32S3 已支持 UART keepalive、返回前缀清洗、RFID WUPA 唤醒、ACK HTTP 回传。
- Web “打开风扇”到 STM32 ACK 已验证。
- RC522 真实卡 UID `436A4B07` 已注册为 `student/study`，RFID 授权扫描到 STM32 ACK 已验证。
- 小程序真实 AppID 已换为 `wx7397c01ea9d04c21`，微信开发者工具可直接打开仓库根目录。
- 浏览器 Web Speech API 语音入口已接入 `/api/asr/recognized`。
- STM32 实时传感器已进入后端：温度、湿度、电位器、距离状态字段；当前超声波多次为 `distance_ok=false`。
- 云端 Qwen-Plus 已启用并实测通过，最近强制云端冒烟结果：`ack_ok_count=12`、`ack_err_count=0`、`pending_action_count=0`。
- 后端测试通过：`python -m pytest backend\tests -q` -> `25 passed, 1 warning`。

## 最新云端对话验收命令

启动后端：

```powershell
python tools\start_backend.py --bind-host 0.0.0.0 --health-host 127.0.0.1 --port 8083 --timeout 20
```

检查后端云端状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8083/api/health | ConvertTo-Json
```

期望看到：

```text
ai_provider=dashscope_openai
ai_model=qwen-plus
cloud_ready=true
```

强制真实云端多轮对话 + STM32 ACK 冒烟：

```powershell
python tools\cloud_dialogue_smoke.py --base-url http://127.0.0.1:8083 --require-cloud --ack-wait-seconds 20
```

期望看到：

```text
cloud_ready=true
cloud_fallback_detected=false
ack_err_count=0
pending_action_count=0
```

## 本轮新增或改动重点

- `backend/app/main.py`：`/api/health` 返回 `ai_model`、`cloud_ready`。
- `backend/app/ai.py`：云端 Qwen 现在被要求只返回结构化 `{"reply","speech"}`，其中 `reply` 给 Web/小程序显示，`speech` 给 SYN6288 做更短播报。
- `backend/app/ai.py`：系统 prompt 已放开为“通用智能助手 + 智能硬件能力”，复杂问题由 Qwen 展开回答，简单控制和状态查询保持短答。
- `backend/app/ai.py`：新闻类问题会先抓取公开 RSS 新闻条目，再交给 Qwen 做中文摘要；无新闻源时要求明确说明不可用，不编造实时新闻。
- `backend/app/schemas.py`：健康检查响应模型增加云端状态字段。
- `backend/app/store.py`：设备状态新增 `last_speech`，用于展示最近一次实际播报短句。
- `backend/app/actions.py`：TTSHEX 按 UTF-8 字节截断到 120 字节，避免云端长回复导致 SYN6288/STM32 ACK ERR。
- `backend/app/static/console.html`、`miniprogram/pages/index/*`：显示最近播报短句，便于答辩时说明“展示文本”和“喇叭播报”分离。
- `tools/cloud_dialogue_smoke.py`：真实云端多轮对话冒烟脚本现在会同时打印 `reply` / `speech` 片段，支持 `--require-cloud`，检测云端兜底，逐轮等待 ACK。
- `backend/tests/test_phase1.py`：增加云端结构化回复、播报短句长度和状态持久化等测试。
- `docs/CLOUD_DIALOGUE_HANDOFF.md`：专门记录云端真实对话交接。
- `docs/ESP32_MIC_ASR_PHASE_PLAN.md`：新增 ESP32S3 板载麦克风短录音上传、真实 Paraformer ASR 和后续实时语音阶段计划。
- `docs/CURRENT_PROGRESS_HANDOFF.md`：已追加 2026-06-11 20:35 云端真实对话验收补充。

## 答辩主线

项目亮点不是固定录音播放，而是：

```text
真实语音/文本输入
-> 后端云端 Qwen-Plus 多轮智能对话
-> 结合温湿度、电位器、距离状态、RFID 用户上下文
-> 生成自然回复和硬件动作
-> ESP32S3 转发给 STM32
-> SYN6288 播报 / OLED 显示 / 风扇等执行
-> STM32 ACK 回传证明闭环
```

推荐现场演示三句话：

```text
你是谁，能像朋友一样陪我聊几句吗？
现在状态怎么样？结合温湿度和距离告诉我。
你记得我刚才问了什么吗？顺便给我一个学习建议。
```

## 重要注意事项

- 不要打印、提交、泄露 `backend/.env`。
- 文档里只能记录 `cloud_ready=true/false`、`ai_provider`、`ai_model` 这种状态，不记录任何 API Key。
- 如果 `/api/health` 显示 `cloud_ready=false`，不能宣称真实云端模型已启用。
- 如果 `cloud_dialogue_smoke.py` 显示 `cloud_fallback_detected=true`，说明云端请求失败并回退本地规则，需要先排查网络、Key 权限或 DashScope 服务状态。
- 云端模型回复已按问题复杂度自适应：复杂问题在 Web/小程序展示完整回答，SYN6288 只播报短 `speech`；后端仍保留 120 字节截断兜底。
- 当前仓库在 git 里整体显示为未跟踪状态，提交前需要特别小心，不要把 `.env` 或无关个人文件加入版本控制。

## 下一步建议

- 下一阶段优先按 `docs/ESP32_MIC_ASR_PHASE_PLAN.md` 推进 ESP32S3 板载麦克风 3 秒短录音上传到 `/api/asr/transcribe`。
- 保留浏览器语音入口作为答辩兜底；硬件麦克风链路没有稳定前，不替换现有 Web Speech 演示路径。
- 演示前再次跑 `tools/cloud_dialogue_smoke.py --require-cloud --ack-wait-seconds 20`。
- 如果现场觉得播报仍偏长，继续微调 `backend/app/ai.py` 里的云端 prompt 和 `SPEECH_MAX_BYTES`。
- 若时间允许，继续排查超声波 `distance_ok=false`，但它不是当前答辩主线阻塞项。
- 小程序端继续保持 `http://127.0.0.1:8083` 模拟器联调；真机预览按局域网 IP 配置。
