# 行动大纲

目标：从空白重建到完整 AI 语音终端，按“少返工、可验证、可答辩”的顺序推进。

## 总原则

1. 先合同，后代码：先固定接线、协议、状态机、验收清单。
2. 先文本，后语音：先证明 AI 与硬件动作闭环，再接 ASR。
3. 先独立，后集成：RFID、SYN6288、STM32 UART、ESP32S3 WiFi 都要先有单项验收。
4. 先本地，后云端：答辩演示优先本地稳定运行，云部署作为增强项。
5. 不把密钥写进仓库：API Key、Wi-Fi 密码只放本地配置。

## 辅助技能

本项目已安装 5 个 Codex skills 辅助后续开发与交付：`playwright`、`transcribe`、`pdf`、`security-best-practices`、`render-deploy`。使用方式见 `docs/SKILLS_APPLIED.md`。

## Phase 0：基线固化

产物：

- `docs/ASSIGNMENT_REQUIREMENTS.md`
- `docs/ENVIRONMENT_BASELINE.md`
- `docs/HARDWARE_WIRING.md`
- `docs/PROTOCOL.md`
- `docs/AI_ASR_DECISION.md`
- `docs/REBUILD_GUARDRAILS.md`

验收：

- 能讲清课程四层架构。
- 能讲清每个硬件模块的角色。
- 能讲清主链路为什么不再用 ESP8266。

## Phase 1：后端最小闭环

开发内容：

- FastAPI 项目骨架。
- 设备状态接口。
- RFID 用户注册接口。
- AI 对话接口。
- 动作队列与 ACK。
- WebSocket 实时会话接口。
- Web 控制台。

验收：

```text
POST /api/chat "你是谁"
-> 返回 AI 回复
-> 生成 tts_speak / oled_display 动作
-> /api/hardware/commands/{device_id} 可取到命令
```

## Phase 2：STM32 执行器闭环

开发内容：

- STM32 `NET:*` 命令解析。
- SYN6288 `NET:TTS:<text>`。
- OLED `NET:OLED:<text>`。
- RGB `NET:AI:IDLE/BUSY/OFF`。
- 蜂鸣器 `NET:BEEP`。
- 风扇 `NET:FAN:ON/OFF`。
- ACK：`BT:ACK:<action_id>:OK/ERR`。

验收：

从 `COM7` 手动发送：

```text
NET:TTS:测试中，请说话
NET:OLED:AI READY
NET:BEEP
NET:FAN:ON:2
NET:FAN:OFF
```

## Phase 3：ESP32S3 桥接闭环

开发内容：

- ESP32S3 连接 Wi-Fi。
- ESP32S3 连接后端 WebSocket。
- ESP32S3 将 `stm32/commands` 转为 UART。
- ESP32S3 读取 STM32 `BT:ACK` 并回传后端。

验收：

```text
后端注入 NET:TTS
-> ESP32S3 COM8 日志显示收到命令
-> STM32 播报
-> STM32 返回 ACK
-> 后端诊断显示 ACK OK
```

## Phase 4：RFID 登录/解锁

开发内容：

- RC522 接 ESP32S3。
- 读取 UID。
- 后端注册卡片。
- 刷卡登录并解锁桌面终端。
- OLED 显示当前用户模式。

验收：

```text
未刷卡：设备锁定，仅显示时间/LOCKED
刷学习卡：进入 study 模式
刷管理员卡：允许配置修改
未注册卡：拒绝登录
```

## Phase 5：语音闭环

开发内容：

- ESP32S3 本地唤醒。
- 唤醒后进入 `listen`。
- 录音并上传 WAV。
- 后端调用 Paraformer ASR。
- ASR 文本进入 Phase 1 文本闭环。

验收：

```text
用户：你好小智
SYN6288：请说话
用户：你是谁
SYN6288：我是你的智能桌面助手
Web 控制台：显示录音字节、ASR 文本、AI 回复、下发命令、ACK
```

## Phase 6：微信小程序

开发内容：

- 设备状态页。
- AI 对话页。
- RFID 用户页。
- 手动控制页。
- 诊断页或演示页。

验收：

- 手机能查看状态。
- 手机能发送对话。
- 手机能手动播报、控制风扇、锁定/解锁。

## Phase 7：答辩打包

产物：

- 课程设计报告。
- 答辩 PPT。
- 成果视频。
- 源码压缩包。
- 演示检查清单。

演示主线：

```text
刷卡解锁 -> Web/小程序显示用户 -> 语音唤醒 -> AI 问答 -> SYN6288 播报 -> OLED/风扇动作 -> 后端诊断证明闭环
```
