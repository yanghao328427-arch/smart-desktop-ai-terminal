---
title: Smart Desktop AI Terminal
emoji: 🖥️
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
- ESP32S3 Sense：WiFi、RFID、STM32 UART 桥接，当前直接接入阿里云 ECS 公网后端。
- FastAPI 后端：设备状态、RFID 用户、AI 对话、动作规划、实时诊断、Web/移动端控制台。
- 应用层：Web 控制台和移动端页面，满足课程设计对 PC/移动应用端的要求。

当前答辩主线不是“播放预设录音”，而是“用户真实输入文本或语音 -> 后端 AI 生成回复 -> STM32 执行并 ACK”的智能对话闭环。

## 当前重建原则

1. 当前答辩主链使用 ESP32S3 -> 阿里云 ECS；WebSocket 为主，HTTP轮询为兜底，本机relay仅保留为应急路径。
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

- 先刷已注册 RFID 卡，或在本次网页会话输入控制口令并选择用户上下文
- 双击 `tools\start_laptop_realtime_listener.cmd`，它默认进入 KEY2 PTT 模式
- 按住 STM32 `KEY2/PB13` 说话，松开后电脑麦克风录音立即上传，后端继续走 AI/TTS/ACK 闭环；短按 KEY2 只终止当前播报

云端模型冒烟测试：

```powershell
python .\tools\cloud_dialogue_smoke.py --base-url http://127.0.0.1:8083
```

输出里的 `cloud_ready=true` 表示后端已使用 DashScope OpenAI-compatible `qwen-plus`；如果是 `false`，系统仍会安全退回本地规则，硬件闭环可继续演示，但不算真实云端模型对话。脚本默认最多等待 10 秒，让 STM32 ACK 回传后再汇总。
云端对话现在会区分完整展示回复 `reply` 和播报短句 `speech`：Web/小程序保留完整文本，SYN6288 优先播报更短的口语句，后端仍保留 120 字节截断兜底。

如果要在答辩前强制检查“必须是真实云端模型”，加上 `--require-cloud`。

答辩现场的只读实时就绪检查：

```powershell
python .\tools\realtime_readiness_check.py
```

该脚本默认访问已部署的阿里云 ECS 服务，只读取健康、设备状态和诊断接口；它要求云端模型和持久化存储就绪、ESP32 在线、WebSocket 会话已连接、UART 正常、错误 ACK 与待执行队列均为 0、最近上报不超过 20 秒，并检测至少两项真实传感器字段。`"verdict": "PASS"` 才表示可以把页面数据作为当场实时数据展示。ESP32 刚重新插入或重启时，先预留 1—3 分钟完成 Wi-Fi/UART 保活启动，再运行此检查。

整套答辩启动（ECS直连检查、必要时启动relay兜底、网页控制台与语音前端）：

```powershell
.\tools\start_defense_demo.cmd
```

启动器检测到ESP32已直连ECS时不会启动relay；通过实时自检后才会打开控制台，并在用户确认后启动 KEY2 触发的笔记本麦克风 PTT 前端。详见 [答辩演示脚本](docs/DEMO_STORYBOARD.md#一键启动整套答辩链路)。

测试：

```powershell
python -m pytest backend/tests -q
```

RFID 用户、卡片绑定、会话和对话上下文会持久化到本机 `backend/data/context.sqlite3`，旧版 `backend/data/rfid_users.json` 只作为迁移来源；这些文件不包含 `backend/.env` 中的任何密钥。
已注册卡刷卡后进入该用户自己的上下文；未知卡或未刷卡状态不能访问用户上下文，除非网页/小程序携带 `CONTROL_TOKEN`。在线注册通过网页/小程序发起后，等待真实 RC522 下一次刷卡完成绑定；手动 UID 仅保留为备选调试入口。真实 ESP32S3 RFID 上报使用独立 `DEVICE_TOKEN`。

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
- [答辩最终运行卡](docs/DEFENSE_FINAL_RUNBOOK_2026-06-24.md)
- [答辩现场运行卡](docs/DEMO_STORYBOARD.md#0-开场自检30-秒)
- [已安装技能与项目应用方式](docs/SKILLS_APPLIED.md)
- [测试计划](docs/TEST_PLAN.md)
- [重建禁区](docs/REBUILD_GUARDRAILS.md)
- [答辩验收清单](docs/ACCEPTANCE_CHECKLIST.md)
- [阿里云 ECS 迁移状态](docs/ALIYUN_ECS_MIGRATION_2026-06-24.md)

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
