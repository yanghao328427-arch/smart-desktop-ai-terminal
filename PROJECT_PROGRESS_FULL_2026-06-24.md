# 智能桌面 AI 终端｜当前项目全量进度总结

更新时间：2026-06-24 02:43（北京时间）
项目路径：`D:\HuaweiMoveData\Users\35267\Documents\New project2`
当前分支：`master`
发布前基线：`34eeae5 Merge Space main deployment branch`

> 本文是当前项目的全量状态快照，覆盖架构、后端、云端、ESP32S3、STM32、传感器、执行器、语音、RFID、网页、小程序、测试、部署、已知风险、冻结范围和下一步。
> 历史上“曾经通过”与“2026-06-24 此刻通过”分开记录；没有把缓存、兜底或局部成功写成实时完成。

---

## 1. 一句话结论

项目已经形成可答辩的真实闭环：

```text
网页 / 微信小程序 / 笔记本麦克风 PTT
                  ↓ HTTPS
Hugging Face FastAPI + DashScope Qwen/ASR
                  ↓ 公网状态、指令和 ACK
本机 ESP32 relay :8091
                  ↓ 局域网 HTTP
ESP32S3 Sense
                  ↓ UART
STM32 学习板
                  ↓
传感器 / OLED / RGB / SYN6288 / 风扇 / 蜂鸣器 / 舵机 / 锁控制
```

截至本次核验：

- Hugging Face 公网服务正在运行。
- 公网 `cloud_ready=true`，AI 为 `dashscope_openai / qwen-plus`。
- 公网实时自检为 `PASS`，ESP32、UART 和真实传感器上报均新鲜。
- STM32 与 ESP32S3 当前源码均能编译。
- 后端自动化测试为 `57 passed, 1 warning`。
- Python 代码和小程序 JavaScript 语法检查通过。
- 网页、小程序、RFID 用户上下文、在线注册、KEY2 PTT、持久化数据库等最新功能已在本地代码中完成。
- 最新一批功能仍处于**大量未提交改动**状态，不能假定已经全部部署到 Hugging Face。
- 当前可靠语音入口是**笔记本麦克风**；ESP32S3 板载麦克风路径仍明确禁用。

---

## 2. 当前真实运行状态

### 2.1 公网主链：通过

公网地址：

- 应用/API：`https://yh001399-smart-desktop-ai-terminal.hf.space`
- 网页控制台：`https://yh001399-smart-desktop-ai-terminal.hf.space/console`
- 健康检查：`https://yh001399-smart-desktop-ai-terminal.hf.space/api/health`
- 设备诊断：`https://yh001399-smart-desktop-ai-terminal.hf.space/api/realtime/diagnostics/desktop-agent-001`

2026-06-24 02:43（北京时间）运行：

```powershell
python .\tools\realtime_readiness_check.py
```

结果：

```text
verdict=PASS
cloud_ready=true
device_online=true
uart_ok=true
state_is_fresh=true
diagnostics_is_fresh=true
enough_sensor_fields=true
edge_id_matches=true
```

当时公网实时快照：

| 字段 | 数值 |
| --- | --- |
| AI provider | `dashscope_openai` |
| AI model | `qwen-plus` |
| edge_id | `esp32s3-sense-001` |
| 状态上报年龄 | `2.4 秒` |
| 诊断上报年龄 | `1.1 秒` |
| 温度 | `27.2 °C` |
| 湿度 | `48.5 %` |
| 距离 | `3.3 cm` |
| 电位器 | `561` |
| NTC 原始值 | `1017` |
| 循迹信号 | `true` |
| 编码器位置 | `-2` |

结论：本次检查时，公网后端、ESP32 上报、STM32 UART 和传感器数据链路都是真实且新鲜的，不是历史缓存。

### 2.2 本机进程

当前监听：

| 端口 | 进程 | 状态 | 作用 |
| --- | --- | --- | --- |
| `8083` | Python/Uvicorn | 正在监听 | 本地 FastAPI 后端 |
| `8091` | `esp32_hf_relay.py` | 正在监听 | ESP32 到 Hugging Face 的本机 relay |

当前未发现运行中的 `laptop_realtime_listener.py`，因此语音 PTT 前端此刻没有启动。

### 2.3 本机 8083 与公网状态为何不同

本机 `http://127.0.0.1:8083` 当前健康检查正常：

```text
status=ok
cloud_ready=true
ai_provider=dashscope_openai
ai_model=qwen-plus
```

但本机设备状态为：

```text
online=false
uart_ok=false
session_connected=false
connection_count=0
```

这是因为当前 ESP32 relay 的主目标是 Hugging Face 公网链，不是本机 8083。它不表示公网硬件离线。当前答辩实时真相应以公网自检和公网诊断为准。

---

## 3. 当前系统边界与云端分工

### 3.1 当前答辩主链

```text
Web / 微信小程序
        ↓ HTTPS
Hugging Face FastAPI
        ├─ DashScope Qwen 对话
        ├─ ASR 接口
        ├─ 设备状态与诊断
        ├─ 动作队列与 ACK
        └─ RFID 用户/上下文接口
        ↓
本机 relay :8091
        ↓
ESP32S3 → STM32 → 实体硬件
```

### 3.2 Hugging Face、华为云 IoTDA、CCI 的角色

| 平台 | 当前角色 | 是否属于答辩主链 |
| --- | --- | --- |
| Hugging Face | FastAPI 公网后端、AI、Web/小程序 API、状态、指令、ACK | 是 |
| DashScope | Qwen 对话与可配置的 Paraformer ASR | 是，云端 AI 能力 |
| 华为云 IoTDA | ESP32 可选并行 MQTT 设备云通道 | 否 |
| 华为云 CCI | 答辩后可选的容器迁移目标 | 否，当前未启用 |

IoTDA 不是“小程序 → IoTDA → Hugging Face”的中转站。当前网页和小程序都直接读取 Hugging Face。

### 3.3 实时性的判定

不能只看 `online=true`。当前后端使用：

```text
DEVICE_ONLINE_TTL_SECONDS = 30
```

设备超过 30 秒没有新的硬件证据后，会自动清除：

- `online`
- `uart_ok`
- `session_connected`

硬件在线证据来自 heartbeat、telemetry、RFID、ACK 和硬件命令流；普通网页聊天或 ASR 文本不会把设备伪装成在线。

---

## 4. 后端进度

### 4.1 FastAPI 主体

后端当前提供：

- 健康检查；
- 设备状态与诊断；
- heartbeat 与 telemetry；
- 动作下发、排队、ACK；
- WebSocket 实时会话；
- AI 文本对话；
- ASR 音频上传、分片上传和已识别文本入口；
- RFID 注册、扫描与在线注册；
- 用户创建、用户列表与上下文切换；
- 网页控制台、移动页；
- 设备新鲜度过期；
- 对话、用户和会话持久化。

当前主要 API：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/health` | 云端、协议和模型健康 |
| GET | `/api/state/{device_id}` | 当前设备快照 |
| GET | `/api/realtime/status` | 实时连接总览 |
| GET | `/api/realtime/diagnostics/{device_id}` | 分层诊断和动作记录 |
| WS | `/api/realtime/ws` | ESP32/WebSocket 实时通道 |
| POST | `/api/hardware/heartbeat` | ESP32 心跳 |
| POST | `/api/hardware/telemetry` | STM32/ESP32 遥测 |
| GET | `/api/hardware/commands/{device_id}` | relay 轮询命令 |
| POST | `/api/hardware/action` | 显式硬件动作 |
| POST | `/api/hardware/ack` | STM32 动作 ACK |
| POST | `/api/hardware/button` | KEY1/KEY2 事件备用上报 |
| POST | `/api/chat` | 文本对话 |
| POST | `/api/asr/transcribe` | 音频识别 |
| POST | `/api/asr/transcribe/chunk` | 音频分片上传 |
| POST | `/api/asr/recognized` | 客户端已识别文本 |
| POST | `/api/realtime/inject` | 实时会话注入 |
| GET | `/api/users` | 用户列表 |
| POST | `/api/users` | 创建用户 |
| POST | `/api/context/select` | 切换用户上下文 |
| POST | `/api/rfid/enroll/start` | 发起在线刷卡注册 |
| GET | `/api/rfid/enroll/{id}` | 查询注册状态 |
| POST | `/api/rfid/enroll/{id}/cancel` | 取消注册 |
| POST | `/api/rfid/register` | 手动 UID 备选绑定 |
| POST | `/api/rfid/scan` | 真实或模拟刷卡 |

### 4.2 AI 对话

已完成：

- DashScope OpenAI-compatible `qwen-plus` 接入；
- `cloud_ready` 明示真实云端配置状态；
- 本地规则兜底，但不会把兜底冒充云端；
- 完整显示回复 `reply` 与硬件短播报 `speech` 分离；
- 复杂问题允许较完整回答；
- 硬件控制回复保持短、可执行；
- 设备状态、传感器、用户和模式进入上下文；
- 支持组合意图，如“打开风扇并进入专注模式”；
- 支持近期多轮对话；
- 新闻类问题可引入公开 RSS 上下文，来源不可用时要求明确说明；
- 长中文播报按 UTF-8 字节安全截断，避免 SYN6288 超长帧失败。

### 4.3 用户、RFID 与长期上下文

最新本地代码已把旧的单文件 RFID 注册升级为 SQLite：

```text
backend/data/context.sqlite3
```

数据库覆盖：

- 用户；
- 卡片与用户绑定；
- 用户会话；
- 对话/记忆事件；
- 用户资料摘要；
- RFID 在线注册请求；
- 审计事件。

旧文件：

```text
backend/data/rfid_users.json
```

现在主要作为历史迁移来源。

当前行为：

- 已注册卡刷卡后创建该用户的活动会话；
- 用户、模式、UID 会通过 `NET:UI:USER` 同步到 STM32；
- 未知卡不会继承上一个用户；
- 未知卡在存在待处理在线注册时，可完成下一次真实刷卡绑定；
- 管理员可用控制口令创建用户、选择上下文和发起在线注册；
- 对话会按用户写入持久化上下文；
- 真实 RC522 与网页模拟扫描具有不同权限来源。

### 4.4 安全和权限边界

项目使用两类口令：

- `CONTROL_TOKEN`：网页/小程序管理员控制、用户管理、在线注册、跨用户操作；
- `DEVICE_TOKEN`：真实 ESP32S3 RFID 等设备侧受保护写入。

约束：

- 两个 token 不应设置为同一个值；
- token 和 API Key 不进入文档、截图或 Git；
- `backend/.env` 是受保护文件；
- ESP32 本地配置和 token 存在本机配置/NVS，不提交真实值；
- 状态读取与诊断可公开，控制与用户管理需要相应上下文或口令。

### 4.5 动作和中断

后端动作层已支持：

- TTS；
- 停止播报；
- 音量；
- OLED；
- 用户上下文；
- 风扇；
- 蜂鸣器/音乐；
- 专注模式；
- 舵机；
- 锁；
- RGB/状态灯。

KEY2 按下时会：

1. 立即产生中断事件；
2. 停止当前 TTS；
3. 标记尚未发送的相关动作被中断；
4. 通知 WebSocket 客户端；
5. 长按后进入笔记本麦克风 PTT 录音。

---

## 5. ESP32S3 进度

### 5.1 当前职责

ESP32S3 负责：

- 连接本机 relay 或后端；
- heartbeat；
- 转发 STM32 telemetry；
- 轮询并转发后端动作；
- 上传 STM32 ACK；
- RC522 真实刷卡；
- 转发 KEY1/KEY2 事件；
- UART 保活与状态判断；
- 可选 IoTDA MQTT 并行上报；
- 本地 NVS 配置服务地址和 token。

### 5.2 UART 链路

当前接线：

```text
ESP32S3 D5/GPIO6/TX  → STM32 PB11/USART3_RX，9600 8N1
STM32 PB3/software TX → ESP32S3 D7/GPIO44/RX，4800 8N1
GND ↔ GND
```

已完成：

- `NET:*` 命令下发；
- `BT:*` ACK、PONG、遥测、按钮事件上行；
- UART keepalive；
- 脏前缀清洗；
- HTTP ACK 优先、WebSocket 备用；
- RFID 扫描去重；
- HALT 卡 `PICC_WakeupA()` 唤醒；
- relay 公网转发。

已知历史风险：

- STM32 → ESP32S3 的 PB3 软件串口偶发首字节脏前缀；
- 当前通过前缀清洗与周期 `NET:UART?` 降级为可接受噪声；
- 如果再次出现真实 action ACK 丢失，才需要逻辑分析仪或重评串口方案。

### 5.3 RC522

接线：

| RC522 | ESP32S3 |
| --- | --- |
| 3V3 | 3V3 |
| GND | GND |
| SCK | D8/GPIO7 |
| MISO | D9/GPIO8 |
| MOSI | D10/GPIO9 |
| SDA/SS | D3/GPIO4 |
| RST | D2/GPIO3 |

真实卡历史验收：

```text
UID=436A4B07
用户=student
模式=study
```

该卡曾完成：

```text
RC522 → ESP32S3 → 后端授权 → TTS/OLED/LOCK → STM32 ACK
```

当前本地代码又新增了在线注册与 SQLite 用户上下文，但这批最新能力仍应在部署后重新用真实卡验收。

### 5.4 板载麦克风边界

当前固件明确：

```text
MIC_PATH_ENABLED=false
```

结论：

- ESP32S3 Sense 板载麦克风采音、大包 Wi-Fi 上传和稳定 ASR 路线没有被宣称解决；
- `CFG:MIC:*` 仍会被拒绝；
- 当前语音主线转为笔记本麦克风；
- ESP32S3 保留硬件桥接、RFID、按钮和 UART 职责。

---

## 6. STM32 固件进度

### 6.1 状态机

当前固件将 UI 与设备状态分为：

```text
S0 BOOT
S1 LOCKED
S2 READY
S3 LISTEN
S4 PROCESS
S5 SPEAK
S6 EXEC
S7 ERROR
```

特性：

- OLED 固定仪表式布局；
- 状态标题、用户、链路、传感器和执行器分屏；
- KEY1 切换信息页，长按回主屏；
- UART/telemetry 不覆盖持久状态；
- LOCKED 保持到真实解锁命令；
- RGB 表达人机交互状态；
- 动作 ID、解析时间、ACK 时间保留在 USB 日志。

### 6.2 KEY1 / KEY2

| 按键 | 引脚 | 当前语义 |
| --- | --- | --- |
| KEY1 | PB12 | 短按切 OLED 信息页，长按回主屏 |
| KEY2 | PB13 | 按下立即中断播报；长按超过约 600ms 启动笔记本 PTT；松开上传 |

KEY2 事件：

```text
BT:BTN:KEY2:DOWN
BT:BTN:KEY2:HOLD_START:<duration_ms>
BT:BTN:KEY2:UP:<duration_ms>
BT:BTN:KEY2:SHORT:<duration_ms>
```

### 6.3 SYN6288

已支持：

```text
NET:TTS:<text>
NET:TTSHEX:<utf8_hex>
NET:TTS:STOP
NET:VOLUME:<0-16|UP|DOWN>
```

实现要点：

- UTF-8 → Unicode → UTF-16BE；
- SYN6288 帧封装和 XOR；
- 长文本安全限制；
- 音量默认 10/16；
- 编码器每格调一级音量；
- 用户主动询问外，音量变化只显示，不重复播报。

历史实机证据：

- 中文播报已被人工听到；
- TTS/TTSHEX 动作收到 STM32 ACK；
- 长回复使用 `speech` 短句避免播报过长。

### 6.4 OLED 与中文字库

当前新增：

```text
firmware/stm32/stm32_executor/oled_cjk16.h
```

用于补充 OLED 中文显示资源。OLED 与 AHT20 共用 I2C：

```text
SCL=PB6
SDA=PB7
```

实测总线历史上可见 AHT20 与 OLED 地址。

### 6.5 编译资源

2026-06-24 当前源码编译通过：

```text
程序存储：60932 / 65536 bytes，92%
动态内存：3660 / 20480 bytes，17%
```

注意：

- Flash 已达到 92%，后续新增固件功能必须关注容量；
- 链接器有 RWX LOAD segment 警告，但本次构建成功；
- 当前验证是编译，不等于本次已重新烧录到板上。

---

## 7. 传感器与执行器

### 7.1 已接入传感器

| 设备 | 引脚 | 状态 |
| --- | --- | --- |
| AHT20 温湿度 | PB6/PB7 I2C | 已接入 telemetry，公网实时有数值 |
| HCSR04 超声波 | TRIG=PA11，ECHO=PA10 | 已接入，公网实时有距离 |
| 电位器 | PA5 | 已接入 |
| NTC | PA4 | 已接入 |
| 循迹模块 | PB14 | 已接入 |
| 旋转编码器 | PA8/PA9/PB15 | 已接入，调音量和 UI |
| RC522 | ESP32S3 SPI | 已完成真实卡历史闭环 |

典型 telemetry：

```json
{
  "pot_raw": 561,
  "ntc_raw": 1017,
  "tracking_signal": true,
  "aht20_ok": true,
  "temperature_c": 27.2,
  "humidity_pct": 48.5,
  "distance_ok": true,
  "distance_cm": 3.3,
  "encoder_position": -2
}
```

### 7.2 执行器

| 设备 | 引脚/链路 | 当前状态 |
| --- | --- | --- |
| 风扇/DRV8833 | PA0/PA1 | 已校正方向，PA1 PWM、PA0 LOW |
| SYN6288 | PB10 USART3_TX | 已播报中文 |
| OLED | PB6/PB7 | 状态机和信息页 |
| RGB | PA6/PA7/PB0 | 当前表达人机状态 |
| 蜂鸣器 | PB9 | 支持提示音和短音乐 |
| 舵机 | PB8 | 支持 `NET:SERVO` |
| 继电器 | PB5 | 保留为独立输出，不是当前风扇 |
| 锁控制 | 协议动作 | RFID 授权链路已使用 |

风扇档位：

```text
NET:FAN:ON:1
NET:FAN:ON:2
NET:FAN:ON:3
NET:FAN:OFF
```

DRV8833 关断：

```text
NET:MOTOR:OFF
```

---

## 8. 语音与人机交互

### 8.1 当前主语音路径

```text
按住 STM32 KEY2
    ↓
STM32 发 KEY2:HOLD_START
    ↓
ESP32S3 转发按钮事件
    ↓
笔记本 PTT 监听器开始录音
    ↓
松开 KEY2，停止并上传
    ↓
/api/asr/transcribe
    ↓
AI reply/speech + 动作规划
    ↓
STM32 TTS/OLED/执行器 + ACK
```

启动入口：

```powershell
.\tools\start_laptop_realtime_listener.cmd
```

当前默认已调整为 KEY2 PTT，而不是始终录音。

### 8.2 其他可用语音入口

- Web 浏览器 `SpeechRecognition`；
- 笔记本 VAD 持续监听；
- 笔记本唤醒词短窗口；
- 手动录音 sidecar；
- `/api/asr/recognized` 已识别文本入口；
- `/api/asr/transcribe` 音频入口；
- 本地 FunASR/SenseVoice 可配置路线；
- DashScope Paraformer 可配置路线。

### 8.3 隐私与准确表述

- PTT 模式只在 KEY2 长按期间录音；
- 短按 KEY2 只停止当前输出；
- 当前没有运行语音监听进程；
- 答辩时应表述为“STM32 实体按键触发笔记本麦克风录音”；
- 不应表述为“ESP32S3 板载麦克风已经完成”。

---

## 9. RFID 与个性化

### 9.1 已完成能力

- 真实 RC522 UID 读取；
- 已登记卡授权；
- 未登记卡拒绝；
- 用户/模式绑定；
- 后端持久化；
- 刷卡后创建活动会话；
- 用户对话记忆；
- OLED 当前用户显示；
- TTS 授权提示；
- 锁与 UI 动作；
- 在线注册下一张真实卡；
- 手动 UID 绑定作为调试备用；
- 网页和小程序用户管理。

### 9.2 当前访问规则

对话或控制需满足其一：

1. 已注册卡形成有效用户上下文；
2. 当前网页/小程序会话输入有效 `CONTROL_TOKEN`。

真实 RC522 上报使用 `DEVICE_TOKEN`。未知卡不会沿用上一位用户。

### 9.3 尚需补做的最新验收

旧版“固定 UID 注册与刷卡”已有实机证据；最新 SQLite/在线注册/用户切换代码是 2026-06-23 的本地改动，建议完成：

```text
网页发起在线注册
→ 刷一张未绑定真实卡
→ enrollment=completed
→ 用户上下文写入 SQLite
→ STM32 显示用户
→ 对话写入该用户记忆
→ 重启后端后仍可恢复
```

---

## 10. 网页控制台

当前网页控制台包含：

- 云端模型状态；
- 设备在线/UART/实时性；
- 真实传感器；
- 最近动作与 ACK；
- AI 完整回复与短播报；
- 文本和浏览器语音入口；
- 用户列表和上下文；
- RFID 在线注册与手动绑定；
- 控制口令输入；
- 预设演示问题；
- 诊断原文；
- 无数据时明确显示 `-`、等待或离线。

原则：

- 不使用随机传感器数值；
- 不伪造在线状态；
- 不因页面刷新就宣称实时；
- 控制动作必须等真实 ACK；
- 公开读状态与受保护写操作分开。

最新 UI 改动仍在本地工作区，需提交并部署后再确认公网控制台是否完全一致。

---

## 11. 微信小程序

### 11.1 基本信息

```text
AppID=wx7397c01ea9d04c21
默认 API=https://yh001399-smart-desktop-ai-terminal.hf.space
体验版本=1.0.0
```

体验二维码：

```text
output/playwright/wechat-experience-qr-only-1.0.0.png
```

### 11.2 已完成

- 仓库根目录可通过 `miniprogramRoot` 打开；
- 默认公网后端；
- 设备、云端、传感器和诊断展示；
- AI 对话；
- 动作/ACK 展示；
- RFID 注册和模拟扫描；
- 用户上下文；
- 控制口令只在当前打开期间使用；
- 无真实数据时不填假值；
- 网页与小程序读取同一 Hugging Face 状态。

### 11.3 当前范围

- 答辩使用体验版；
- 由项目管理员本人扫码演示；
- 未加入体验成员的账号不能随意使用；
- 本阶段不继续做备案、正式发布和全网开放；
- 手机无需与电脑同一 Wi-Fi，但 ESP32 仍需访问本机 relay 的局域网地址。

### 11.4 最新代码状态

小程序 2026-06-23 又有大幅界面和用户/RFID 流程改动。JavaScript 语法已通过，但仍需：

- 微信开发者工具重新运行；
- 真机体验版重新上传；
- 验证控制口令；
- 验证在线注册；
- 验证用户上下文；
- 确认合法域名和当前版本一致。

---

## 12. 一键答辩启动

入口：

```powershell
.\tools\start_defense_demo.cmd
```

或：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\start_defense_demo.ps1
```

启动顺序：

1. 检查本机 relay；
2. relay 缺失时只启动一份；
3. 循环运行公网实时就绪检查；
4. 只有 `PASS` 后才打开网页控制台；
5. 经用户确认后启动笔记本麦克风前端；
6. 默认使用 KEY2 PTT。

边界：

- 不改网络；
- 不改 VPN；
- 不改 DNS；
- 不改路由；
- 不改防火墙；
- 不自动下发聊天或硬件动作；
- 不重复启动 relay；
- 硬件刚上电需额外等待 1—3 分钟，自检本身不代表硬件启动时间。

---

## 13. 通信协议

### 13.1 包装命令

```text
NET:CMD:<action_id>:<inner_command>
```

主要命令：

```text
NET:TTSHEX:<utf8_hex>
NET:TTS:STOP
NET:VOLUME:<0-16|UP|DOWN>
NET:OLED:<text>
NET:UI:USER:<user_id>:<uid>:<mode>
NET:FAN:ON:<1-3>
NET:FAN:OFF
NET:BEEP
NET:MUSIC:<type>
NET:SERVO:<0-180>
NET:LOCK:ON
NET:LOCK:OFF
NET:AI:BUSY
NET:AI:IDLE
NET:UART?
NET:TELEMETRY?
```

返回：

```text
BT:ACK:<action_id>:OK
BT:ACK:<action_id>:ERR
BT:PONG:<uptime_ms>
BT:{telemetry_json}
BT:BTN:<event>
BT:LOCK:ON
BT:LOCK:OFF
```

### 13.2 ACK 原则

- 后端生成动作 ID；
- ESP32S3 转发包装命令；
- STM32 执行；
- STM32 返回相同 action ID；
- ESP32S3 上传 ACK；
- 后端更新 `ack_ok_count`、`ack_err_count` 和 pending；
- 页面只能在真实 ACK 后显示完成。

---

## 14. 测试与构建结果

### 14.1 后端测试

2026-06-24：

```text
57 passed, 1 warning
```

覆盖范围包括：

- 健康检查；
- 云端配置；
- 对话和动作；
- TTS 长度；
- ACK；
- telemetry；
- 设备 30 秒过期；
- RFID 持久化；
- SQLite 重启恢复；
- 在线刷卡注册；
- 用户上下文；
- KEY2 事件；
- 权限；
- ASR；
- 协议映射。

唯一警告来自 FastAPI TestClient 依赖的 Starlette/httpx 弃用提示，不是测试失败。

### 14.2 Python 和 JavaScript

```text
python -m compileall -q backend\app tools
PASS

node --check miniprogram\app.js
PASS

node --check miniprogram\pages\index\index.js
PASS
```

### 14.3 STM32

```text
编译通过
Flash 92%
RAM 17%
```

### 14.4 ESP32S3

```text
编译通过
程序存储 927573 / 3342336 bytes，27%
动态内存 46484 / 327680 bytes，14%
```

### 14.5 Git 基础检查

```text
git diff --check
```

未发现空白错误；只出现 Windows 下 LF 将来可能转 CRLF 的提示。

---

## 15. Git、部署和工作区状态

### 15.1 远端

```text
origin = https://github.com/yanghao328427-arch/smart-desktop-ai-terminal.git
space  = https://huggingface.co/spaces/yh001399/smart-desktop-ai-terminal
```

### 15.2 分支关系

```text
本地 master: 34eeae5
origin/master: 41f614d
space/master: 766368c
```

本地 `master` 相对本机记录的 `origin/master` 显示 `ahead 6`。

### 15.3 未提交改动

当前工作区不是干净状态：

- 30 个已跟踪文件有修改；
- 约 `3248 insertions / 892 deletions`；
- 还有多项未跟踪文件和目录。

主要未跟踪内容：

```text
STAGE_SUMMARY.md
backend/app/context_db.py
backend/data/
firmware/stm32/stm32_executor/oled_cjk16.h
tools/realtime_readiness_check.py
tools/start_defense_demo.cmd
tools/start_defense_demo.ps1
```

重要结论：

- 当前公网链路本身已通过实时检查；
- 但 2026-06-23/24 的 SQLite、用户、PTT、UI、固件状态机等本地改动不能自动视为已进入公网部署；
- 提交前需先确认 `backend/data/` 中哪些是运行数据，避免把本地 SQLite、音频、日志或用户数据提交；
- `backend/.env`、真实 token、Wi-Fi 密码必须继续排除。

---

## 16. 历史关键里程碑

### 2026-06-10：后端与设备桥接基础

- FastAPI Phase 1；
- 基础设备状态/API；
- ESP32S3 与 STM32 协议入口；
- 8083 本地后端启动工具；
- WebSocket 与调试工具。

### 2026-06-11：TTS、RFID、云端 AI、传感器

- STM32 支持 `NET:TTSHEX`；
- SYN6288 中文实际播报；
- Web“打开风扇”到 STM32 ACK；
- 真实 RC522 卡 `436A4B07` 闭环；
- RFID 持久化；
- AHT20、电位器 telemetry；
- 浏览器真实语音入口；
- DashScope Qwen 真实云端对话；
- `reply` 与 `speech` 分离；
- 多轮对话和通用问答；
- 小程序开发者工具初步联调。

### 2026-06-12：语音与硬件边界排查

- ESP32S3 板载麦克风短录音/上传路线尝试；
- KEY2、ASR、大包 Wi-Fi 上传问题拆分；
- 明确不能用固定文本冒充硬件语音完成；
- 保留浏览器/电脑语音兜底。

### 2026-06-13：笔记本麦克风路线与硬件补齐

- 语音主线转为笔记本麦克风；
- laptop mic sidecar 验证；
- VAD/唤醒词/KEY2 旁路设计；
- 风扇 DRV8833 方向修正；
- 蜂鸣器引脚修正为 PB9；
- 超声波、NTC、循迹、编码器、舵机接入；
- RGB 传感器状态语义；
- 一键语音监听器。

### 2026-06-20—22：公网部署与答辩收口

- Hugging Face 公网部署；
- `cloud_ready=true`；
- ESP32 到公网真实数据；
- 微信体验版 1.0.0；
- 网页与小程序无假数据；
- 30 秒设备在线过期；
- 只读实时自检；
- 一键答辩启动器；
- 明确 Hugging Face 主链、IoTDA 并行、CCI 未来迁移；
- 答辩范围收束为本人扫码体验版。

### 2026-06-23—24：个性化、PTT 与产品化

- SQLite 用户/卡片/会话/记忆；
- 在线刷卡注册；
- 用户上下文动作；
- KEY2 按下中断、长按 PTT、松开上传；
- OLED 持久状态机与用户信息页；
- 网页/小程序用户和注册 UI；
- 设备/控制 token 分离；
- 最新测试增至 57 项；
- 两套固件再次编译通过；
- 公网实时检查继续为 PASS。

---

## 17. 已完成、条件完成、未完成

### 17.1 已完成并有当前证据

- Hugging Face 公网服务运行；
- DashScope Qwen 云端就绪；
- 公网真实硬件实时上报；
- UART 当前正常；
- 真实温湿度、距离等传感器上报；
- 本机 relay 正在运行；
- 设备 30 秒过期机制；
- 后端 57 项测试；
- STM32 当前源码可编译；
- ESP32S3 当前源码可编译；
- Python/小程序 JS 语法通过；
- 答辩自检和启动器代码存在。

### 17.2 历史已完成，但应在最终版本重新验收

- 风扇实体动作；
- SYN6288 中文播报；
- RFID 卡 `436A4B07` 授权；
- TTS/OLED/FAN/LOCK ACK 闭环；
- 浏览器语音；
- 笔记本麦克风语音；
- 小程序体验版状态读取；
- 微信端实际控制；
- 在线注册和 SQLite 用户流；
- KEY2 长按 PTT 完整实体闭环。

原因：这些功能有历史证据或本地测试，但最新代码、部署版本和当前实体固件之间仍需做一次同版本联合验收。

### 17.3 明确未完成或主动冻结

- ESP32S3 板载麦克风稳定采音与上传；
- 板载麦克风实时流式 ASR；
- 正式发布微信小程序；
- 微信备案、全网开放；
- 任意微信账号体验；
- CCI 正式迁移；
- IoTDA 作为主业务链；
- 历史趋势与长期云数据库；
- 最新本地大改动的完整 Git 提交与公网部署；
- 当前最新版本的完整答辩彩排录像/证据包。

---

## 18. 当前风险

### P0：必须处理

1. **发布时必须保持源码与运行数据边界。**
   SQLite、音频、密钥和临时构建物不得进入版本库；提交前应继续执行忽略规则和敏感值检查。

2. **公网部署后仍需核对实际版本。**
   推送成功不等于 Space 已完成构建，应重新读取公网健康接口和网页内容确认版本生效。

3. **最终实体联合验收尚需重跑。**
   需要用同一版本完成 RFID、PTT、AI、TTS、风扇和 ACK。

4. **STM32 Flash 已使用 92%。**
   后续继续加字库或功能可能超容量。

### P1：答辩稳定性

1. Hugging Face 免费 Space 可能冷启动；
2. ESP32 重新供电后可能需要 1—3 分钟；
3. PB3 软件串口可能出现脏前缀；
4. 现场网络/VPN 不应临时大改；
5. 小程序体验版受微信账号权限限制；
6. 当前 PTT 依赖答辩电脑麦克风；
7. 语音前端与串口工具不能争用资源；
8. 距离 `3.3 cm` 属于很近的快照，现场展示应注意传感器前方物体。

### P2：产品化

- 后端内存设备状态在进程重启后清零；
- SQLite 是本机文件，尚未形成公网持久数据库方案；
- 缺少完整历史趋势；
- 缺少正式用户权限系统；
- 缺少正式发布、运维和监控；
- 部分文档仍保留早期局域网/旧语音路线，应以本文和最新协议为准。

---

## 19. 推荐的下一步顺序

### 第一步：保护并整理当前工作区

1. 不动 `backend/.env`；
2. 检查 `.gitignore`；
3. 排除：
   - `backend/data/context.sqlite3`
   - 用户数据；
   - 音频；
   - 日志；
   - `local_config.h`
   - token；
4. 将源码、文档、工具与运行数据分开；
5. 形成一个可复现提交。

### 第二步：同版本编译、烧录、部署

1. 编译并烧录当前 STM32；
2. 编译并烧录当前 ESP32S3；
3. 提交后端/网页/小程序；
4. 推送 GitHub；
5. 更新 Hugging Face；
6. 确认 `cloud_ready=true`；
7. 重新上传微信体验版。

### 第三步：完整联合验收

按顺序执行：

```text
公网 readiness PASS
→ 网页和小程序看到同一组传感器
→ 创建用户
→ 发起 RFID 在线注册
→ 刷未绑定真实卡
→ SQLite 持久化
→ KEY2 长按 PTT 说“打开风扇”
→ ASR 文本正确
→ Qwen reply/speech 正确
→ STM32 OLED/TTS/风扇执行
→ action ACK 成功
→ 重启后端
→ 用户/卡片仍存在
```

### 第四步：答辩彩排

3—5 分钟建议：

1. 运行只读自检并展示 `PASS`；
2. 展示实体硬件和实时传感器；
3. 网页与小程序显示同一状态；
4. 刷卡切换用户；
5. 长按 KEY2 说话；
6. 展示 AI 完整回答与 SYN6288 短播报；
7. 展示风扇/其他低风险动作；
8. 展示 ACK；
9. 说明 Hugging Face、DashScope、IoTDA 和 CCI 的边界；
10. 主动说明语音采集来自笔记本麦克风。

---

## 20. 答辩当天最小检查表

```text
[ ] ESP32S3、STM32、传感器和执行器已供电
[ ] 本机 8091 relay 只有一个监听实例
[ ] 不改网络/VPN/DNS/路由/防火墙
[ ] python .\tools\realtime_readiness_check.py 返回 PASS
[ ] cloud_ready=true
[ ] online=true
[ ] uart_ok=true
[ ] last_seen 不超过 20 秒
[ ] 至少两项真实传感器存在
[ ] 网页控制台能打开
[ ] 本人微信能进入体验版
[ ] 控制口令只在需要时输入，不展示
[ ] 已注册卡可切换用户
[ ] KEY2 短按可中断播报
[ ] KEY2 长按 PTT 可录音并识别
[ ] 至少一个低风险动作收到真实 ACK
[ ] SYN6288 音量和清晰度已现场确认
[ ] 二维码、控制台、健康检查、诊断页已提前打开或收藏
```

---

## 21. 关键文件索引

### 总览与答辩

```text
README.md
STAGE_SUMMARY.md
PROJECT_PROGRESS_FULL_2026-06-24.md
docs/ARCHITECTURE.md
docs/DEMO_STORYBOARD.md
docs/ACCEPTANCE_CHECKLIST.md
docs/TEST_PLAN.md
```

### 后端

```text
backend/app/main.py
backend/app/store.py
backend/app/context_db.py
backend/app/ai.py
backend/app/asr.py
backend/app/actions.py
backend/app/schemas.py
backend/app/static/console.html
backend/tests/
```

### ESP32S3

```text
edge/esp32s3/main/main.ino
edge/esp32s3/README.md
tools/configure_esp32.py
tools/esp32_hf_relay.py
```

### STM32

```text
firmware/stm32/stm32_executor/stm32_executor.ino
firmware/stm32/stm32_executor/oled_cjk16.h
firmware/stm32/README.md
docs/HARDWARE_WIRING.md
docs/PROTOCOL.md
```

### 语音

```text
tools/laptop_realtime_listener.py
tools/start_laptop_realtime_listener.cmd
tools/laptop_mic_sidecar.py
tools/laptop_wakeword_sidecar.py
docs/LOCAL_ASR_FUNASR.md
```

### 部署与启动

```text
tools/realtime_readiness_check.py
tools/start_defense_demo.cmd
tools/start_defense_demo.ps1
docs/PUBLIC_DEPLOYMENT.md
docs/HUAWEI_CCI_DEPLOYMENT.md
Dockerfile
render.yaml
```

### 小程序

```text
project.config.json
miniprogram/app.js
miniprogram/pages/index/
docs/MINIPROGRAM_PLAN.md
```

---

## 22. 最终原则

1. 真实数据优先于“看起来正常”。
2. `cloud_ready=true` 才能宣称真实云端模型已启用。
3. `online=true` 必须同时结合新鲜 `last_seen`。
4. 动作成功必须有真实 STM32 ACK。
5. 网页和小程序必须读取同一后端真相。
6. 笔记本麦克风路线和 ESP32S3 板载麦克风路线必须分开表述。
7. Hugging Face 是当前主链，IoTDA 是并行扩展，CCI 是未来方案。
8. `backend/.env`、API Key、token、Wi-Fi 密码和本地用户数据不得泄露或提交。
9. 当前最重要的工作不是继续堆功能，而是整理版本、统一部署、完成同版本实体联合验收。
