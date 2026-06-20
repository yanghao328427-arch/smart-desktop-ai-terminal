---
title: Smart Desktop AI Terminal
emoji: desktop_computer
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---

# 智能桌面 AI 终端重建工程

这是物联网工程综合课程设计的新基线工程。旧项目不再继续补丁式开发，本仓库从统一协议、状态机和分层验收重新搭建。

## 目标

构建一个基于 STM32F103、XIAO ESP32S3 Sense、SYN6288 TTS 和 RC522 RFID 的桌面级智能 AI 终端：

- STM32：本地传感器采集、OLED、RGB、蜂鸣器、风扇、舵机、SYN6288 播报。
- ESP32S3 Sense：WiFi、语音唤醒/录音入口、WebSocket 实时会话、RFID、STM32 UART 桥接。
- FastAPI 后端：设备状态、RFID 用户、AI 对话、动作规划、实时诊断、Web/移动端控制台。
- 应用层：Web 控制台和移动端页面，满足课程设计对 PC/移动应用端的要求。

当前答辩主线不是“播放预设录音”，而是“用户真实输入文本或语音 -> 后端 AI 生成回复 -> STM32 执行并 ACK”的智能对话闭环。

## 当前重建原则

1. 主链路只保留 ESP32S3 WebSocket 实时会话，不再把 ESP8266 HTTP 作为主线。
2. 先稳定文本闭环：`用户问题 -> 后端 Agent -> STM32 命令 -> TTS/OLED/执行器`。
3. 音频流在文本闭环稳定后接入，优先采用 WebSocket 二进制帧或有 ACK 的分片。
4. RFID 独立验收后再并入主链路，避免调试复杂度叠加。
5. 所有状态灯必须来自统一会话状态，不再用“绿灯亮”代表系统健康。

## 快速启动

```powershell
python -m pip install -r backend/requirements.txt
python .\tools\start_backend.py
```

启动脚本会在后端可用后主动请求 `/api/health`，并打印类似结果：

```json
{
  "status": "ok",
  "protocol": "smart-desktop-realtime-v1",
  "ai_provider": "mock",
  "ai_model": "local-rules",
  "cloud_ready": false,
  "device_id": "desktop-agent-001",
  "edge_id": "esp32s3-sense-001"
}
```

如果只运行原始 `uvicorn` 前台命令，它只会启动服务和打印访问日志，不会自动调用健康检查接口；需要另开终端请求健康检查。

终端 1：

```powershell
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8083 --reload
```

终端 2：

```powershell
cd backend
Invoke-RestMethod http://127.0.0.1:8083/api/health | ConvertTo-Json
```

页面：

- `http://127.0.0.1:8083/console`
- `http://127.0.0.1:8083/mobile`
- `http://127.0.0.1:8083/docs`

语音演示：

- 在 Chrome / Edge 打开 `http://127.0.0.1:8083/console`
- 点击“开始语音”并允许麦克风权限
- 直接说“你是谁”或“打开风扇”，浏览器会完成真实语音识别，后端继续走 AI/TTS/ACK 闭环

云端模型冒烟测试：

```powershell
python .\tools\cloud_dialogue_smoke.py --base-url http://127.0.0.1:8083
```

输出里的 `cloud_ready=true` 表示后端已使用 DashScope OpenAI-compatible `qwen-plus`；如果是 `false`，系统仍会安全退回本地规则，硬件闭环可继续演示，但不算真实云端模型对话。脚本默认最多等待 10 秒，让 STM32 ACK 回传后再汇总。
云端对话现在会区分完整展示回复 `reply` 和播报短句 `speech`：Web/小程序保留完整文本，SYN6288 优先播报更短的口语句，后端仍保留 120 字节截断兜底。

如果要在答辩前强制检查“必须是真实云端模型”，加上 `--require-cloud`。

测试：

```powershell
python -m pytest backend/tests -q
```

RFID 注册会持久化到本机 `backend/data/rfid_users.json`，用于避免后端重启后丢失已登记卡片；该文件不包含 `backend/.env` 中的任何密钥。

## 目录

- `docs/`：课程要求、总架构、硬件接线、协议、测试计划和重建禁区。
- `backend/`：FastAPI 后端最小可运行闭环。
- `edge/esp32s3/`：ESP32S3 Sense 固件脚手架和主链路说明。
- `firmware/stm32/`：STM32 协议执行器脚手架。
- `tools/`：启动与诊断脚本。

## 关键文档

- [行动大纲](docs/ACTION_OUTLINE.md)
- [环境与实物基线](docs/ENVIRONMENT_BASELINE.md)
- [AI 与 ASR 选型决策](docs/AI_ASR_DECISION.md)
- [课程任务书要求整理](docs/ASSIGNMENT_REQUIREMENTS.md)
- [总体架构](docs/ARCHITECTURE.md)
- [硬件接线基线](docs/HARDWARE_WIRING.md)
- [通信协议](docs/PROTOCOL.md)
- [微信小程序路线](docs/MINIPROGRAM_PLAN.md)
- [本地密钥与配置](docs/LOCAL_SECRET_CONFIG.md)
- [答辩演示脚本](docs/DEMO_STORYBOARD.md)
- [已安装技能与项目应用方式](docs/SKILLS_APPLIED.md)
- [测试计划](docs/TEST_PLAN.md)
- [重建禁区](docs/REBUILD_GUARDRAILS.md)
- [答辩验收清单](docs/ACCEPTANCE_CHECKLIST.md)

## 最短验收闭环

```text
用户：你好小智
STM32/SYN6288：请说话
用户：你是谁
后端：生成 AI 回复与 NET:TTS 命令
ESP32S3：转发 NET:CMD:<id>:NET:TTSHEX:<utf8_hex>
STM32：执行并回复 BT:ACK:<id>:OK
Web 控制台：显示 ASR/文本、回复、命令、ACK 和设备状态
```
