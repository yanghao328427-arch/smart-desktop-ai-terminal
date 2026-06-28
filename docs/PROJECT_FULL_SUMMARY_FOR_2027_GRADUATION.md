# 智能桌面 AI 终端项目总结与 2027 毕业设计完全体路线

整理时间：2026-06-28  
整理范围：当前仓库、历史交接文档、后端/固件/小程序源码、部署与答辩资料  
当前分支：`codex/voice-stable-pre-wakenet-20260625`  
当前定位：课程设计可答辩版本已经形成，后续可作为毕业设计继续产品化、工程化和论文化。

> 本文用于明年继续推进毕业设计时快速接手。它不替代现有协议、接线、部署和测试文档，而是把项目“已经有什么、证据在哪里、哪些不能夸大、下一年怎么做成完全体”整理成一份总览。

---

## 1. 项目一句话定义

本项目是一套基于 STM32F103、XIAO ESP32S3 Sense、RFID、真实传感器、云端大模型、Web 控制台和微信小程序的智能桌面 AI 终端。

它的核心不是单纯聊天，也不是固定录音或网页模拟，而是：

```text
真实用户输入 / RFID 身份 / 环境传感器
        -> FastAPI 平台层
        -> DashScope Qwen / Paraformer
        -> 动作规划
        -> ESP32S3 网络桥接
        -> STM32 本地执行
        -> OLED / SYN6288 / RGB / 风扇 / 蜂鸣器 / 舵机 / 锁
        -> STM32 ACK 回传
        -> Web / 小程序 / 诊断页展示闭环证据
```

项目价值在于把“感知、身份、对话、执行、验证”连成同一条物联网闭环，而不是只把 AI 回复显示在屏幕上。

---

## 2. 当前真实状态

### 2.1 当前仓库基线

当前代码分支为：

```text
codex/voice-stable-pre-wakenet-20260625
```

最近提交聚焦于：

- 稳定语音主链保存；
- WakeNet 迁移前回退基线；
- 隔离的 ESP-SR WakeNet 探针；
- 二进制回退与受控测试说明。

本次整理时运行：

```powershell
python -m pytest backend\tests -q
```

结果：

```text
71 passed, 1 warning
```

警告来自 FastAPI / Starlette TestClient 依赖的弃用提示，不是业务测试失败。

### 2.2 当前主链判断

较早阶段项目使用 Hugging Face Space 作为公网后端；较新的文档、启动器和小程序默认地址已经转向阿里云 ECS：

```text
公网 HTTPS：https://8-163-38-158.sslip.io
后端部署：阿里云 ECS，Ubuntu 22.04，FastAPI + Uvicorn + Nginx
小程序默认 API：https://8-163-38-158.sslip.io
```

因此明年接手时应按下面口径理解：

| 平台 | 当前角色 |
| --- | --- |
| 阿里云 ECS | 当前主业务链，承载 FastAPI、Qwen、ASR、SQLite、Web/API |
| Hugging Face Space | 历史公网部署和备用参考，不再作为最新主链 |
| 华为云 IoTDA | 并行设备云扩展思路，不是 Web/AI/RFID 主业务中转 |
| 华为云 CCI | 早期容器迁移备选，不是当前已启用主链 |

注意：部分历史文档仍保留 Hugging Face 作为主链的描述。明年写论文或答辩材料时，应以 `docs/ARCHITECTURE.md`、`docs/ALIYUN_ECS_MIGRATION_2026-06-24.md`、当前小程序默认地址和启动器脚本为准，并在需要时说明“项目经历了 Hugging Face 到阿里云 ECS 的迁移”。

### 2.3 不能夸大的边界

以下内容不能写成已经完全完成：

- ESP32S3 板载麦克风稳定采音、上传和实时 ASR 仍未成为主链；
- WakeNet 已有隔离探针工程，但不是已接管生产语音入口；
- 微信小程序正式发布仍依赖自有域名、备案、HTTPS 合法域名配置和重新上传；
- 临时 `sslip.io` 域名适合调试和答辩，不适合作为正式毕业设计产品域名；
- STM32 Flash 已接近容量上限，继续增加大字库和复杂 UI 会有风险；
- 设备是否实时在线必须以 readiness 检查、时间戳、传感器新鲜度和 ACK 为准，不能只看页面能打开。

---

## 3. 项目结构总览

```text
backend/                 FastAPI 后端、AI/ASR、状态、动作、SQLite、测试
backend/app/static/      Web 控制台页面
backend/tests/           后端和协议自动化测试
edge/esp32s3/            当前稳定 Arduino ESP32S3 固件
edge/esp32s3_wakenet_probe/
                         隔离 ESP-IDF WakeNet 探针工程
firmware/stm32/          STM32 执行器固件、协议参考、OLED 字库
miniprogram/             微信小程序
tools/                   启动、诊断、relay、语音监听、配置和冒烟测试脚本
deploy/                  ECS、Docker、Nginx、CCI 等部署资料
docs/                    设计、协议、接线、测试、部署、答辩和交接文档
outputs/                 答辩 PPT、演示包、讲稿等产物
```

关键入口文件：

| 模块 | 文件 |
| --- | --- |
| 后端 API | `backend/app/main.py` |
| 运行时状态 | `backend/app/store.py` |
| SQLite 上下文 | `backend/app/context_db.py` |
| AI 规划 | `backend/app/ai.py` |
| ASR | `backend/app/asr.py` |
| 动作到协议映射 | `backend/app/actions.py` |
| 数据模型 | `backend/app/schemas.py` |
| Web 控制台 | `backend/app/static/console.html` |
| ESP32S3 稳定固件 | `edge/esp32s3/main/main.ino` |
| WakeNet 探针 | `edge/esp32s3_wakenet_probe/` |
| STM32 固件 | `firmware/stm32/stm32_executor/stm32_executor.ino` |
| 小程序 | `miniprogram/pages/index/` |
| 一键启动 | `tools/start_defense_demo.cmd`、`tools/start_defense_demo.ps1` |
| readiness | `tools/realtime_readiness_check.py` |

---

## 4. 课程设计阶段已完成的能力

### 4.1 四层物联网架构

| 层级 | 本项目实现 |
| --- | --- |
| 感知与执行层 | STM32F103、AHT20、HCSR04、电位器、NTC、循迹、编码器、RC522、OLED、RGB、SYN6288、风扇、蜂鸣器、舵机、锁 |
| 网络层 | ESP32S3 Wi-Fi、HTTP/HTTPS、WS/WSS、UART、必要时本机 relay |
| 平台层 | FastAPI、设备状态、动作队列、ACK、RFID 用户、SQLite、DashScope Qwen、Paraformer ASR、诊断接口 |
| 应用层 | Web 控制台、微信小程序、移动页、答辩启动器、演示 GUI/脚本 |

### 4.2 AI 与硬件闭环

已形成主链：

```text
Web/小程序/语音文本
-> /api/chat 或 /api/asr/*
-> Qwen 或本地规则兜底
-> reply/speech 分离
-> 动作列表
-> NET:CMD:<action_id>:NET:*
-> ESP32S3
-> STM32
-> BT:ACK:<action_id>:OK/ERR
-> 后端诊断更新
```

其中：

- `reply` 面向 Web/小程序完整展示；
- `speech` 面向 SYN6288 做短播报；
- 后端仍有 UTF-8 字节安全截断，避免长中文导致 STM32 或 SYN6288 失败；
- 没有 ACK 的动作不能宣称执行成功。

### 4.3 RFID 个性化

RFID 已从“刷卡开锁”升级为用户上下文入口：

- RC522 真实读卡；
- UID 绑定用户、模式；
- 已登记卡授权，未知卡拒绝；
- 刷卡后进入当前用户会话；
- 用户上下文同步到 STM32，OLED 可显示用户信息；
- 对话事件写入 SQLite；
- 支持网页/小程序发起在线注册，下一张真实卡完成绑定；
- `CONTROL_TOKEN` 和 `DEVICE_TOKEN` 分离。

历史实机证据中，真实卡：

```text
UID=436A4B07
用户=student
模式=study
```

已完成过 RFID 授权到 STM32 TTS/OLED/LOCK/ACK 闭环。明年应重新使用最新版本做同版本复验。

### 4.4 语音入口

当前稳定路线：

```text
KEY2 / 浏览器 / 笔记本麦克风
-> 录音或识别文本
-> Paraformer 或 Web Speech
-> 后端同一条 AI/动作/ACK 链
```

关键原则：

- 笔记本麦克风是真实语音输入，但采音设备不是 ESP32S3 板载麦克风；
- KEY2 可作为实体触发入口，长按进入 PTT，短按中断播报；
- WakeNet 目前作为隔离探针存在，尚未接管主链；
- 明年毕业设计可以把板载唤醒和板载采音作为重点提升点。

### 4.5 Web 控制台与小程序

已具备：

- 云模型状态；
- 设备在线与 UART 状态；
- 传感器展示；
- 文本 AI 对话；
- 动作、ACK、pending 队列；
- RFID 用户与在线注册；
- 控制口令；
- 诊断原文；
- 无数据时显示离线、等待或空值，不填假数。

小程序当前默认：

```text
https://8-163-38-158.sslip.io
```

但正式发布需要自有域名、备案和微信合法域名配置。

---

## 5. 硬件设计总结

### 5.1 主控分工

| 设备 | 职责 |
| --- | --- |
| STM32F103 | GPIO、传感器采集、OLED、RGB、蜂鸣器、风扇、舵机、SYN6288、按键、本地状态机、ACK |
| XIAO ESP32S3 Sense | Wi-Fi、后端连接、UART 桥接、RC522、按钮事件转发、ACK 上传、WakeNet 实验探针 |

分层好处：

- STM32 负责确定性控制，不受公网变化影响；
- ESP32S3 负责联网和协议转换；
- 出错时可分层定位：云端、网络、串口、执行器。

### 5.2 核心接线

| 链路 | 接线/引脚 |
| --- | --- |
| ESP32S3 -> STM32 | ESP32S3 D5/GPIO6/TX -> STM32 PB11/USART3_RX，9600 |
| STM32 -> ESP32S3 | STM32 PB3 software TX -> ESP32S3 D7/GPIO44/RX，4800 |
| STM32 -> SYN6288 | STM32 PB10/USART3_TX -> SYN6288 RXD |
| OLED/AHT20 | STM32 PB6/PB7 I2C |
| HCSR04 | TRIG=PA11，ECHO=PA10 |
| 电位器 | PA5 |
| NTC | PA4 |
| 循迹 | PB14 |
| 编码器 | PA8/PA9/PB15 |
| KEY1 | PB12 |
| KEY2 | PB13 |
| 蜂鸣器 | PB9 |
| 风扇 DRV8833 | PA1 PWM，PA0 LOW/方向 |
| 继电器 | PB5 |
| 舵机 | PB8 |
| RC522 -> ESP32S3 | SCK D8/GPIO7，MISO D9/GPIO8，MOSI D10/GPIO9，SS D3/GPIO4，RST D2/GPIO3 |

### 5.3 已接入传感器

- AHT20 温湿度；
- HCSR04 超声波距离；
- 电位器；
- NTC；
- 循迹模块；
- 旋转编码器；
- RC522 RFID；
- KEY1/KEY2 按键事件。

### 5.4 已接入执行器

- OLED；
- SYN6288 中文播报；
- RGB 状态灯；
- 风扇三级控制；
- 蜂鸣器提示音/短音乐；
- 舵机；
- 锁控制协议；
- 专注模式显示；
- TTS 中断和音量控制。

---

## 6. 后端平台总结

### 6.1 主要 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 健康、协议、AI、持久化状态 |
| GET | `/api/state/{device_id}` | 设备状态 |
| POST | `/api/auth/verify` | 管理密码验证 |
| GET/POST | `/api/users` | 用户列表/创建 |
| POST | `/api/context/select` | 切换用户上下文 |
| POST | `/api/rfid/enroll/start` | 发起在线刷卡注册 |
| GET/POST | `/api/rfid/enroll/{id}` | 查询/取消注册 |
| POST | `/api/rfid/register` | 手动 UID 绑定 |
| POST | `/api/rfid/scan` | 真实或模拟刷卡 |
| POST | `/api/hardware/telemetry` | 遥测上报 |
| POST | `/api/hardware/heartbeat` | 心跳上报 |
| GET | `/api/hardware/commands/{device_id}` | HTTP 命令轮询兜底 |
| POST | `/api/hardware/action` | 显式硬件动作 |
| POST | `/api/hardware/ack` | ACK 回传 |
| POST | `/api/hardware/button` | 按键事件 |
| POST | `/api/chat` | 文本对话 |
| POST | `/api/asr/transcribe` | 音频上传识别 |
| POST | `/api/asr/transcribe/chunk` | 分片音频上传 |
| POST | `/api/asr/recognized` | 客户端已识别文本入口 |
| POST | `/api/realtime/inject` | 实时会话注入 |
| GET | `/api/realtime/status` | 实时连接总览 |
| GET | `/api/realtime/diagnostics/{device_id}` | 分层诊断 |
| WS | `/api/realtime/ws` | 实时 WebSocket |

### 6.2 数据与状态

后端同时维护：

- 当前设备状态；
- 传感器快照；
- `last_seen` 和新鲜度；
- UART 状态；
- WebSocket 会话；
- pending / sent / acked 动作；
- ACK 成功与失败计数；
- 最近 RFID；
- 当前用户、模式、会话；
- 最近对话；
- 最近 ASR 结果；
- 最近播报短句；
- 按键事件和中断序列。

设备在线判断不能只靠布尔值，必须结合 30 秒新鲜度、传感器、诊断和 readiness。

### 6.3 SQLite 上下文

当前 `context_db.py` 支持：

- 用户；
- RFID 卡片；
- 用户会话；
- 对话/记忆事件；
- 用户摘要；
- 在线注册请求；
- 审计事件；
- 从旧 `rfid_users.json` 迁移。

毕业设计完全体中，SQLite 可以继续作为单机版本，也可以升级为 PostgreSQL / MySQL，并保留迁移脚本。

### 6.4 安全边界

已形成双 token 思路：

| Token | 用途 |
| --- | --- |
| `CONTROL_TOKEN` | 管理员控制、用户管理、在线注册、未刷卡时访问对话/控制 |
| `DEVICE_TOKEN` | 真实 ESP32S3/RC522 设备侧上报 |

原则：

- 两者不要设置成同一个值；
- API Key、token、Wi-Fi 密码只存在 `.env`、云端 Secret、设备 NVS 或受保护配置；
- 文档、PPT、日志、截图不出现密钥；
- 网页状态读取和控制写入权限分离。

---

## 7. 通信协议总结

### 7.1 设备命令

生产下发统一包装：

```text
NET:CMD:<action_id>:<inner_command>
```

常见内部命令：

```text
NET:TTSHEX:<utf8_hex>
NET:TTS:<text>
NET:TTS:STOP
NET:VOLUME:<0-16|UP|DOWN>
NET:OLED:<text>
NET:UI:USER:<user_id>:<uid>:<mode>
NET:FAN:ON:<1-3>
NET:FAN:OFF
NET:BEEP
NET:MUSIC:<SUCCESS/ALERT/SCALE/STARTUP/BIRTHDAY/STOP>
NET:SERVO:<0-180>
NET:LOCK:ON
NET:LOCK:OFF
NET:AI:BUSY
NET:AI:IDLE
NET:UART?
NET:TELEMETRY?
```

### 7.2 设备回传

```text
BT:ACK:<action_id>:OK
BT:ACK:<action_id>:ERR
BT:PONG:<uptime_ms>
BT:{telemetry_json}
BT:BTN:KEY1:PAGE:<index>
BT:BTN:KEY1:HOME
BT:BTN:KEY2:DOWN
BT:BTN:KEY2:HOLD_START:<duration_ms>
BT:BTN:KEY2:UP:<duration_ms>
BT:BTN:KEY2:SHORT:<duration_ms>
```

### 7.3 ACK 原则

每个动作必须满足：

```text
后端生成 action_id
-> ESP32S3 转发 NET:CMD
-> STM32 执行
-> STM32 返回同 action_id 的 BT:ACK
-> ESP32S3 上传 ACK
-> 后端更新状态
-> Web/小程序展示执行结果
```

这条原则应继续保留到毕业设计完全体，是系统可信度的关键。

---

## 8. 部署与运行总结

### 8.1 当前 ECS 结构

历史文档记录的 ECS 结构：

```text
/opt/smartdesk/releases/<UTC timestamp>
/opt/smartdesk/current
/opt/smartdesk/venv
/var/lib/smartdesk
/etc/smartdesk.env
/etc/systemd/system/voice-iot.service
/etc/nginx/sites-available/voice-iot
```

特点：

- FastAPI + Uvicorn 单 worker；
- Nginx 反向代理；
- SQLite 放在 `/var/lib/smartdesk/context.sqlite3`；
- Secret 写入 `/etc/smartdesk.env`；
- 部署工具位于 `deploy/aliyun-ecs/`；
- 保留 rollback 脚本。

单 worker 是有原因的：当前运行时设备状态和 WebSocket 会话主要在进程内，多个 worker 会造成状态分裂。毕业设计完全体若要多 worker，需要先把设备状态、队列、会话广播迁移到 Redis 或数据库。

### 8.2 启动与诊断命令

本地后端：

```powershell
python .\tools\start_backend.py
```

测试：

```powershell
python -m pytest backend\tests -q
```

云端对话冒烟：

```powershell
python .\tools\cloud_dialogue_smoke.py --require-cloud
```

只读实时检查：

```powershell
python .\tools\realtime_readiness_check.py
```

答辩启动：

```powershell
.\tools\start_defense_demo.cmd
```

### 8.3 readiness 应检查的内容

明年完全体应继续保留并增强 readiness：

- `cloud_ready=true`；
- `persistent_storage=true`；
- `device_online=true`；
- `uart_ok=true`；
- WebSocket 或 HTTP 硬件证据新鲜；
- state 与 diagnostics 时间戳新鲜；
- 至少两项真实传感器字段存在；
- pending 队列为 0 或可解释；
- `ack_err_count` 没有新增异常；
- edge_id 与设备配置匹配。

---

## 9. 测试与证据总结

### 9.1 自动化测试

当前后端测试结果：

```text
71 passed, 1 warning
```

测试覆盖方向包括：

- 健康检查；
- 云端配置；
- persistent storage 标记；
- 文本对话；
- 动作规划；
- TTS 分句和长度；
- ACK；
- telemetry；
- 设备过期；
- RFID 持久化；
- SQLite 恢复；
- 在线注册；
- 用户上下文；
- 权限；
- KEY2 事件；
- ASR；
- WebSocket；
- 固件协议映射。

### 9.2 固件和实机证据

历史文档记录过：

- STM32 编译通过；
- ESP32S3 编译通过；
- STM32 Flash 接近 92% 到 93%；
- ESP32S3 Flash 约 27%；
- SYN6288 中文播报人工听到；
- 风扇动作闭环；
- RC522 真实卡闭环；
- telemetry 进入后端；
- DashScope Qwen 强制云端冒烟通过；
- Paraformer ASR 路线可用；
- WakeNet 探针 ESP-IDF 编译通过，但未接管主链。

明年必须重新做“同一版本”的联合验收，因为历史证据跨越多个阶段和部署目标。

---

## 10. 历史阶段脉络

### 2026-06-10：重建基线

- 重新搭建 FastAPI 后端；
- 固定协议、状态机和目录；
- 形成文本闭环目标；
- 明确不继续旧项目补丁式开发。

### 2026-06-11：硬件闭环突破

- STM32 支持 `NET:TTS` / `NET:TTSHEX`；
- SYN6288 中文播报成功；
- Web“打开风扇”到 STM32 ACK；
- RC522 真实卡 UID `436A4B07` 完成授权闭环；
- 浏览器语音入口；
- DashScope Qwen 云端对话；
- 多轮对话和状态感知。

### 2026-06-12 至 2026-06-13：语音和传感器扩展

- 尝试 ESP32S3 板载麦克风；
- 明确板载麦克风不稳定；
- 语音主线转为笔记本/浏览器麦克风；
- KEY2 物理触发、PTT 设计；
- 风扇、蜂鸣器、超声波、NTC、循迹、编码器、舵机等补齐；
- OLED/RGB 状态系统增强。

### 2026-06-20 至 2026-06-22：公网与小程序

- Hugging Face 公网部署；
- Web 和小程序读取同一后端；
- 不使用假传感器数据；
- readiness 只读检查脚本；
- 微信体验版；
- 答辩启动器。

### 2026-06-23 至 2026-06-24：个性化与 ECS 迁移

- SQLite 用户、卡片、会话和记忆；
- 在线刷卡注册；
- 控制/设备 token 分离；
- KEY2 中断和 PTT；
- 迁移到阿里云 ECS；
- 持久化存储；
- HTTP/WSS 混合链路；
- ECS 上真实 ACK 验收。

### 2026-06-25：稳定语音基线与 WakeNet 探针

- 保存 WakeNet 迁移前稳定基线；
- 后端测试达到 70+；
- STM32/ESP32 回退二进制保存；
- 建立隔离 ESP-IDF WakeNet probe；
- 明确 WakeNet 未完成生产接入。

---

## 11. 当前主要风险

### 11.1 工程风险

- STM32 Flash 空间紧张；
- PB3 软件串口曾出现脏前缀，当前靠清洗和 keepalive 兜底；
- 单 worker 后端不适合横向扩展；
- SQLite 适合单机，产品化需要数据库和迁移；
- 临时域名不适合正式小程序；
- 免费或临时公网环境可能冷启动、限流或证书问题。

### 11.2 演示风险

- 设备刚上电需要 1 到 3 分钟；
- 传感器数据可能因摆放变化异常；
- 语音依赖电脑麦克风和现场噪声；
- 小程序体验版受账号和合法域名限制；
- 网络或 DNS 变化会影响公网后端；
- readiness 没有 PASS 时不能强行说实时在线。

### 11.3 论文风险

- 不要把“历史通过”写成“当前版本已稳定量产”；
- 不要把板载 WakeNet 探针写成完整语音助手；
- 不要把模拟 RFID 写成真实刷卡；
- 不要把发送动作写成执行成功；
- 不要在论文、PPT、附录中泄露 token、API Key、Wi-Fi 密码。

---

## 12. 明年毕业设计完全体目标

建议毕业设计主题：

```text
基于多模态感知与云端大模型的智能桌面交互终端设计与实现
```

完全体目标可以定义为：

1. 实体终端一体化：STM32、ESP32S3、传感器、执行器、外壳、电源和线束整理成可长期运行的桌面设备。
2. 语音完全体：板载或独立语音硬件完成本地唤醒、稳定录音、ASR、打断和播报屏蔽。
3. 云平台完全体：自有域名、HTTPS/WSS、正式数据库、日志、监控、备份和部署流水线。
4. 应用完全体：Web 控制台、小程序正式体验路径、用户权限、历史趋势和设备管理。
5. AI 完全体：设备状态、用户偏好、历史对话、场景模式共同进入 AI 决策，并有可解释动作规划。
6. 测试完全体：自动化测试、硬件回归、长时间稳定性、网络故障恢复和安全测试。
7. 论文完全体：需求、架构、硬件、协议、平台、算法/AI、测试、结果和展望形成完整闭环。

---

## 13. 2027 推进路线

### 阶段 A：开题前整理

目标：把现在的项目从“答辩工程”整理成“毕业设计基线”。

任务：

- 清理 Git 工作区，区分源码、运行数据、输出产物；
- 固定一个 `main` 或 `graduation-baseline` 分支；
- 补一份干净的架构图、接线图和模块图；
- 重跑后端测试；
- 重编译 STM32 和 ESP32S3；
- 重新完成一次同版本联合验收；
- 整理所有密钥和部署配置，不把真实值写进仓库；
- 确定正式题目和论文创新点。

验收：

```text
后端测试通过
STM32/ESP32 编译通过
ECS health 正常
readiness PASS
RFID -> 用户上下文 -> AI -> 动作 -> ACK 成功
```

### 阶段 B：硬件产品化

目标：从散线演示转为稳定桌面终端。

任务：

- 重新设计供电，区分逻辑电源、执行器电源和音频电源；
- 用端子、排线、固定座整理传感器与执行器；
- 为 OLED、RFID、麦克风、按键、风扇设计外壳布局；
- 给关键接口加防反接、防松动和标签；
- 做 8 到 24 小时通电测试；
- 记录温度、联网、ACK、错误率。

建议新增：

- 电源状态检测；
- 看门狗；
- 故障灯码；
- 简单恢复按钮；
- 统一设备序列号。

### 阶段 C：语音完全体

目标：解决当前最大边界：板载或终端侧语音。

路线 1：继续 ESP32S3 WakeNet + PDM 麦克风

- 先在 `edge/esp32s3_wakenet_probe/` 完成唤醒词硬件验收；
- 加入 KEY2 优先级；
- 播报期间屏蔽 WakeNet；
- 唤醒后触发电脑/后端录音或板端短录音；
- 分阶段接入生产固件。

路线 2：外接更适合的语音硬件

- 使用 USB 麦克风阵列、树莓派、语音识别模块或独立语音前端；
- KEY2 仍作为实体触发；
- 后端协议保持不变，只替换采音前端。

阶段验收必须区分：

```text
唤醒成功率
误唤醒率
录音成功率
ASR 准确率
端到端延迟
打断成功率
播报期间自激/回声情况
```

### 阶段 D：平台完全体

目标：把 ECS 演示部署升级为可长期运行服务。

任务：

- 购买或使用自有域名；
- 完成备案和 HTTPS 证书；
- 配置正式 WSS；
- ESP32 走域名和证书链验收；
- 用 PostgreSQL 或 MySQL 替代单文件 SQLite，或明确 SQLite 单机边界；
- Redis 管理动作队列、WebSocket 广播和设备状态；
- 加入日志、监控、告警、备份；
- 设计数据库迁移；
- 提供版本回滚。

建议指标：

- API 可用性；
- 平均响应延迟；
- 设备在线新鲜度；
- ACK 成功率；
- ASR 平均耗时；
- LLM 平均耗时；
- 失败重试次数。

### 阶段 E：应用完全体

目标：Web 与小程序从“答辩控制台”升级为“用户可用应用”。

Web：

- 设备总览；
- 用户管理；
- RFID 卡片管理；
- 历史趋势；
- 对话记录；
- 动作审计；
- 故障诊断；
- 固件版本显示；
- 权限角色。

小程序：

- 自有备案域名；
- 正式合法域名；
- 体验版/正式版重新上传；
- 用户登录或管理员授权；
- 设备绑定；
- RFID 在线注册；
- 语音/文本控制；
- 状态与历史展示。

UI 原则：

- 不显示假数据；
- 数据过期必须明显提示；
- 控制动作必须有 ACK 状态；
- 危险动作需要二次确认或权限；
- 诊断信息对开发者足够透明，对普通用户足够简洁。

### 阶段 F：AI 场景化

目标：让 AI 不只会回答和开风扇，而是具备桌面助手价值。

建议场景：

- 学习模式：结合时间、温湿度、距离、用户偏好给出学习建议；
- 专注模式：计时、打断、环境提示、OLED 状态；
- 休息模式：提醒休息、调低风扇、播放提示音；
- 访客模式：未知 RFID 限制权限；
- 管理员模式：设备诊断、重新注册卡、查看日志；
- 环境助手：根据温湿度和距离给出建议；
- 桌面安全：锁定、解锁、异常刷卡审计。

AI 设计要点：

- 保留本地规则兜底；
- 云端失败必须明确标记；
- 高风险控制不要完全交给模型自由生成；
- 动作规划要结构化；
- 每次动作记录来源、用户、原因和 ACK。

### 阶段 G：论文与成果材料

最终应形成：

- 论文正文；
- 源码仓库；
- 硬件实物；
- 接线图；
- 架构图；
- 协议说明；
- 数据库设计；
- 测试报告；
- 演示视频；
- PPT；
- 用户手册；
- 部署手册；
- 故障处理手册。

---

## 14. 毕业论文建议结构

### 第 1 章 绪论

- 研究背景；
- 智能桌面终端和智能家居现状；
- 传统控制方式不足；
- 大模型接入物联网的意义；
- 本项目目标与主要工作。

### 第 2 章 需求分析与总体方案

- 功能需求；
- 非功能需求；
- 四层架构；
- 硬件选型；
- 软件选型；
- 云端与边缘分工。

### 第 3 章 硬件系统设计

- STM32 最小系统；
- ESP32S3 网络模块；
- 传感器设计；
- RFID 设计；
- 执行器设计；
- 电源和接线；
- 外壳与结构。

### 第 4 章 通信协议与嵌入式软件

- UART 协议；
- `NET:CMD` 与 `BT:ACK`；
- STM32 状态机；
- ESP32S3 桥接；
- 心跳、遥测、按钮和 RFID；
- 异常和重试。

### 第 5 章 云平台与应用系统

- FastAPI 架构；
- 数据模型；
- SQLite/数据库；
- WebSocket 与 HTTP；
- Web 控制台；
- 微信小程序；
- 部署与运维。

### 第 6 章 AI 对话与语音交互

- Qwen 接入；
- Paraformer ASR；
- reply/speech 分离；
- 动作规划；
- 用户上下文；
- WakeNet 或语音前端改进；
- 安全兜底。

### 第 7 章 测试与结果分析

- 单元测试；
- 接口测试；
- 固件测试；
- 联合闭环测试；
- 语音测试；
- RFID 测试；
- 稳定性测试；
- 延迟和成功率分析。

### 第 8 章 总结与展望

- 已完成工作；
- 创新点；
- 不足；
- 后续产品化方向。

---

## 15. 建议创新点表述

可以重点写 4 个创新或特色点：

1. 身份驱动的 AI 桌面终端：RFID 不只是门禁，而是用户上下文、权限和个性化记忆入口。
2. 云边协同的可验证执行闭环：云端 AI 生成动作，STM32 执行并通过同 action_id ACK 证明结果。
3. 多源感知融合：温湿度、距离、电位器、NTC、循迹、按键和 RFID 共同进入状态展示和 AI 上下文。
4. 可靠性优先的分层通信：WebSocket 实时通道与 HTTP 兜底并存，设备在线由新鲜硬件证据判断。

不要把“用了大模型”本身当作唯一创新点。更有价值的是“大模型如何受约束地控制实体硬件，并可被验证”。

---

## 16. 明年接手第一周清单

```text
[ ] 阅读本文
[ ] 阅读 README.md
[ ] 阅读 docs/ARCHITECTURE.md
[ ] 阅读 docs/PROTOCOL.md
[ ] 阅读 docs/HARDWARE_WIRING.md
[ ] 阅读 docs/ALIYUN_ECS_MIGRATION_2026-06-24.md
[ ] 阅读 docs/WAKE_NET_ROLLBACK_BASELINE_2026-06-25.md
[ ] 运行 python -m pytest backend\tests -q
[ ] 检查 backend/.env 是否只在本机存在且不提交
[ ] 启动本地后端并访问 /api/health
[ ] 编译 STM32
[ ] 编译 ESP32S3
[ ] 回看 WakeNet 探针，不直接覆盖稳定固件
[ ] 检查 ECS 是否仍可访问
[ ] 用 readiness 获取当前真实状态
[ ] 重新做 RFID -> AI -> 动作 -> ACK 联合验收
[ ] 给当前硬件拍照并整理接线
[ ] 规划毕业设计题目、开题报告和阶段甘特图
```

---

## 17. 最小复现闭环

明年如果只想最快证明项目还活着，按这个顺序：

1. 后端测试：

```powershell
python -m pytest backend\tests -q
```

2. 健康检查：

```powershell
Invoke-RestMethod https://8-163-38-158.sslip.io/api/health | ConvertTo-Json
```

3. readiness：

```powershell
python .\tools\realtime_readiness_check.py
```

4. 打开 Web 控制台：

```text
https://8-163-38-158.sslip.io/console
```

5. 刷已注册 RFID 卡。

6. 输入：

```text
打开风扇
```

7. 观察：

```text
后端动作生成
ESP32S3 转发
STM32 执行
BT:ACK:<action_id>:OK
Web/小程序诊断更新
```

如果这个最小闭环通过，说明毕业设计主干仍可继续推进。

---

## 18. 完全体验收指标建议

| 类别 | 指标 |
| --- | --- |
| 后端 | 自动化测试通过率 100%，核心接口平均响应可记录 |
| 设备在线 | 连续运行 8 到 24 小时，设备状态不误判 |
| ACK | 常用动作 ACK 成功率可统计，失败有原因 |
| RFID | 已登记卡识别成功率、未知卡拒绝、在线注册成功 |
| 语音 | 唤醒率、误唤醒率、ASR 准确率、端到端延迟 |
| AI | 云端可用时真实 Qwen，云端不可用时明确降级 |
| 传感器 | 至少两类真实传感器长期刷新 |
| 小程序 | 自有域名 + 合法域名 + 真机验收 |
| 数据 | 用户/卡片/对话/动作审计可持久化 |
| 安全 | 密钥不入库、不入 Git、不进截图 |

---

## 19. 最终建议

明年不要从“再加一个炫酷功能”开始，而应先把当前闭环稳定、复验、文档化，然后再推进完全体。推荐顺序是：

```text
整理基线
-> 同版本实机验收
-> 硬件结构与供电产品化
-> 自有域名和平台持久化
-> 板载/终端侧语音完全体
-> Web/小程序用户体验完善
-> 长时间稳定性和测试报告
-> 论文、PPT、视频收口
```

这个项目已经具备毕业设计的主体骨架：硬件丰富、软件完整、协议清晰、AI 有实际用途、Web 和小程序都有展示面。明年的重点不是推翻重做，而是把它从“能答辩的工程样机”推进成“可长期运行、可解释、可测试、可交付的智能终端完全体”。
