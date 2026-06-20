# 当前进度交接：智能桌面 AI 终端

更新时间：2026-06-11 18:33 +08:00  
仓库路径：`D:\HuaweiMoveData\Users\35267\Documents\New project2`

## 一句话状态

硬件闭环已经打通，且小程序开发者工具联调已走通第一步：ESP32S3 已入网并连接后端，Web 文本“打开风扇”可以经后端 WebSocket 下发到 ESP32S3，再到 STM32，并收到 STM32 ACK 回传。STM32 已正式支持 `NET:TTS` / `NET:TTSHEX` 转 SYN6288 中文播报帧，且用户已人工听到多条播报声音；RC522 真实卡 UID `436A4B07` 已读到、注册为 `student/study`，RFID 授权扫描已触发 TTS/OLED/LOCK 并收到 STM32 ACK。微信开发者工具已能正确打开 `miniprogram/`，真实 AppID 已换成 `wx7397c01ea9d04c21`，模拟器用 `http://127.0.0.1:8083` 保存后端地址已成功。USART3 “每批第一行被吞”问题已降级为低影响串口返回链路脏前缀，当前用 ESP32S3 侧保活和前缀清洗兜住，不阻塞继续开发。

## 答辩主线提醒

- 当前项目的亮点与重点是“智能对话终端”，不是“固定录音播放”或“预设音频触发器”。
- 答辩时应突出：
  - 用户真实说话或真实输入文本
  - 后端 AI 根据当轮输入生成回复
  - 回复再转成 `TTS/OLED/FAN/LOCK` 等动作
  - STM32 返回 `ACK` 证明执行闭环
- 不要把项目描述成“提前录好几句音频再播放”的演示；录音/语音识别只是进入 AI 对话链路的入口。

## 安全提醒

- 不要改动、打印、提交或泄露 `backend/.env`。
- 文档里只允许写 `WIFI_SSID=SET`、`WIFI_PASSWORD=SET`、`API_KEY=SET` 这类占位信息。
- 当前测试后端使用局域网地址和 8083 端口，真实 Wi-Fi 密码/API Key 留在本机 `.env` 内。

## 当前硬件接线

详见 `docs/HARDWARE_WIRING.md`。本轮没有改线，也决定暂时跳过“换其他串口”方案。

| 链路 | 接线 | 参数/用途 |
| --- | --- | --- |
| ESP32S3 -> STM32 | ESP32S3 `D5/GPIO6/TX` -> STM32 `PB11/USART3_RX` | `9600 8N1`，下发 `NET:*` |
| STM32 -> ESP32S3 | STM32 `PB3/software TX` -> ESP32S3 `D7/GPIO44/RX` | `4800 8N1`，返回 `BT:*` |
| STM32 -> SYN6288 | STM32 `PB10/USART3_TX` -> SYN6288 `RXD` | SYN6288 文本播报 |
| STM32 USB 调试 | STM32 `PA2/PA3 USART2` -> COM7 | 调试日志和直连命令 |
| ESP32S3 USB 调试 | ESP32S3 USB -> COM8 | 配置、烧录、日志 |

额外串口结论：STM32F103 上理论还有 `USART1 PA9/PA10`，但 `PA9` 当前被旋转编码器占用；`USART1` remap 到 `PB6/PB7` 又会冲突 I2C OLED/AHT20。因此目前不换硬件串口，优先保留现接线。

## 本轮已完成

### 1. STM32 正式支持 SYN6288 中文播报

文件：

```text
firmware/stm32/stm32_executor/stm32_executor.ino
```

已实现内容：

- 支持 `NET:TTS:<utf8_text>`。
- 支持 `NET:TTSHEX:<utf8_hex>`。
- 支持包装命令 `NET:CMD:<action_id>:NET:TTSHEX:<utf8_hex>`。
- STM32 将 UTF-8 解码为 Unicode 码点，再编码为 UTF-16BE。
- SYN6288 使用帧格式：`0xFD + len + 0x01 + type=0x03 + UTF-16BE payload + xor`。
- 支持 BMP 字符和补充平面代理对，限制 SYN 文本 payload 不超过 200 字节。
- 非法 HEX、非法 UTF-8、超长文本会返回 `BT:ACK:<id>:ERR` 或 `BT:ERR`。

已验证：

```text
CFG:TTS:打开风扇
[STM32 TX] NET:TTSHEX:[12 bytes]
[STM32 RX] BT:OK
```

说明：串口协议 ACK 已验证；2026-06-11 用户补充确认昨天的几条播报都已听到声音。后续只在清晰度、音量或供电不稳定时再调 SYN6288 细节。

### 2. STM32 串口对象已显式化

同一文件中已避免依赖 BluePill variant 是否提供 `Serial3`：

```cpp
HardwareSerial usbConsole(PA3, PA2);
HardwareSerial espCommandSerial(PB11, PB10);
SoftwareSerial espAckSerial(PB4, PB3);
```

用途：

- `usbConsole`：COM7 调试和直连输入。
- `espCommandSerial`：STM32 USART3，接收 ESP32S3 命令，同时 PB10 发 SYN6288。
- `espAckSerial`：STM32 PB3 软件串口，向 ESP32S3 返回 `BT:*`。

### 3. ESP32S3 已移除 TTS 临时替代逻辑

文件：

```text
edge/esp32s3/main/main.ino
```

已完成：

- 移除 TTS/TTSHEX -> `NET:OLED:VOICE READY` 的临时映射。
- WebSocket `speak` 和 `CFG:TTS:` 均通过 `utf8Hex()` 发送 `NET:TTSHEX:<hex>`。
- STM32 返回行增加前缀清洗：如果一行不是 `BT:` 或 `{` 开头，会裁剪到第一个 `B` 或 `{`。
- 增加 UART keepalive：链路空闲且 ACK/PONG 过期时自动发送 `NET:UART?`。

保活参数：

```text
UART_OK_WINDOW_MS=15000
UART_KEEPALIVE_INTERVAL_MS=10000
UART_TX_QUIET_MS=7000
```

### 4. 首行被吞问题已降级

原始现象：

```text
ESP32S3 发第一行 NET:UART?
STM32 USB 日志偶见 ESP RX:
```

后续实测又抓到一类更明确的样本：

```text
RAW b'[STM32 RX] \xfeBT:PONG:211954\r\n'
```

当前判断：

- 主问题不再像是 STM32 USART3 入站解析真正吞了后端 action。
- 更像是 STM32 -> ESP32S3 的 PB3 软件串口返回链路，首个 `BT:PONG` 偶发带 `0xFE` 脏前缀。
- ESP32S3 侧前缀清洗和周期性 `NET:UART?` 已能把这个问题变成无害噪声。
- 不建议现在为此改线，除非后续又出现 action ACK 丢失。

### 5. 编译和烧录已完成

STM32：

```powershell
arduino-cli compile --fqbn STMicroelectronics:stm32:GenF1:pnum=BLUEPILL_F103C8 firmware\stm32\stm32_executor
openocd.exe -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program .tmp/build-stm32/stm32_executor.ino.elf verify reset exit"
```

ESP32S3：

```powershell
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
arduino-cli upload -p COM8 --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
```

本地环境备注：

- STM32 Arduino core 2.4.0 已安装到 Arduino15 packages。
- 本机用 Arm GNU Toolchain 14.2 通过目录适配满足旧 core 的工具链路径。
- 本地 STM32 core 的 `dtostrf.c` 曾补过 `<stdint.h>` 以兼容新 GCC；这是 Arduino15 本机环境改动，不在仓库内。

### 6. RFID 模拟闭环已通过

2026-06-11 14:25 左右，后端仍运行在 8083，ESP32S3 会话在线且 `uart_ok=true`。已用演示 UID 走通：

```text
POST /api/rfid/register uid=DEMO0001 name=RFID Demo mode=demo
POST /api/rfid/scan uid=DEMO0001
```

后端生成并经实时通道下发：

```text
NET:CMD:<tts_id>:NET:TTSHEX:[41 bytes]
NET:CMD:<oled_id>:NET:OLED:DEMO MODE
NET:CMD:<lock_id>:NET:LOCK:OFF
```

STM32 均返回 `BT:ACK:<id>:OK`，诊断结果更新为：

```text
ack_ok_count=27
ack_err_count=0
pending_action_count=0
last_rfid_uid=DEMO0001
last_rfid_authorized=true
```

说明：这次验证的是后端注册/扫描、WebSocket 下发、ESP32S3 转发、STM32 执行 ACK 的闭环。

### 7. RC522 真实刷卡闭环已通过

真实卡 UID：

```text
436A4B07
```

已注册为：

```text
name=student
mode=study
```

实测流程：

```text
[RFID] 436A4B07
[HTTP] POST /api/rfid/scan -> 200
[STM32 TX] NET:CMD:<tts_id>:NET:TTSHEX:[37 bytes]
[STM32 TX] NET:CMD:<oled_id>:NET:OLED:STUDY MODE
[STM32 TX] NET:CMD:<lock_id>:NET:LOCK:OFF
[STM32 RX] BT:ACK:<tts_id>:OK
[HTTP] POST /api/hardware/ack -> 200
[STM32 RX] BT:ACK:<oled_id>:OK
[HTTP] POST /api/hardware/ack -> 200
[STM32 RX] BT:ACK:<lock_id>:OK
[HTTP] POST /api/hardware/ack -> 200
```

当前后端诊断：

```text
online=true
uart_ok=true
session_connected=true
last_rfid_uid=436A4B07
last_rfid_authorized=true
current_user=student/study
ack_ok_count=28
ack_err_count=0
pending_action_count=0
```

### 8. ESP32S3 RFID/ACK 加固已刷入

文件：

```text
edge/esp32s3/main/main.ino
```

已完成：

- 同 UID 短时间去重从 5 秒调整为 15 秒：同一张卡短时间重复读到会打印 `[RFID] repeat skipped <UID>`，不会再次 POST `/api/rfid/scan`。
- 常规 `PICC_IsNewCardPresent()` 读不到时，额外使用 `PICC_WakeupA()` 唤醒 HALT 状态的卡，方便卡贴在 RC522 上时重新识别。
- STM32 `BT:ACK:*` 回传优先使用 HTTP `POST /api/hardware/ack`，HTTP 不通时再退回 WebSocket。
- RFID HTTP 扫描响应不再由 ESP32S3 直接转发命令，避免刚重连时和 WebSocket/轮询兜底重复下发同一批动作。

已完成：

```powershell
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
arduino-cli upload -p COM8 --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
```

刷录后验证：

```text
online=true
uart_ok=true
session_connected=true
last_rfid_uid=436A4B07
last_rfid_authorized=true
ack_ok_count=28
ack_err_count=0
pending_action_count=0
```

### 9. 小程序与微信开发者工具联调已推进

本轮新增并验证：

- 小程序默认后端地址已统一为 `8083`，并增加 5 秒自动刷新、状态摘要、最近动作、诊断原文、真实卡/演示卡预填。
- 根目录 `project.config.json` 已增加 `miniprogramRoot: "miniprogram/"`，因此微信开发者工具可直接打开整个仓库目录，不会再因根目录缺少 `app.json` 而启动失败。
- 真实 AppID 已写入：

```text
wx7397c01ea9d04c21
```

- 已同步到：

```text
project.config.json
miniprogram/project.config.json
```

- `project.private.config.json` 和项目配置中的 `urlCheck` 已关闭，便于本地开发期直连 `http://127.0.0.1:8083` / `http://192.168.0.39:8083`。
- `tools/start_backend.py`、`tools/configure_esp32.py`、`tools/backend_smoke.py`、`README.md`、`docs/LOCAL_SECRET_CONFIG.md` 的默认端口已统一改为 `8083`，避免文档和工具链错位。

开发者工具报错与结论：

- 之前的“`app.json` 未找到”是因为开发者工具把仓库根目录当成了小程序源码根目录；现已通过 `miniprogramRoot` 修正。
- 本机环境变量存在代理：

```text
ALL_PROXY=socks5://127.0.0.1:7897
HTTP_PROXY=http://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897
```

- 后端本身无故障，已实测以下地址都可从本机 PowerShell 返回 `health.status=ok`：

```text
http://127.0.0.1:8083/api/health
http://192.168.0.39:8083/api/health
```

- 但微信开发者工具模拟器保存 `http://192.168.0.39:8083` 时出现 `HTTP 502`，当前判断更像开发者工具请求链路受本机代理/VPN 干扰。
- 当前稳定做法：
  - 开发者工具模拟器里填 `http://127.0.0.1:8083`
  - 真机预览/手机联调时填 `http://192.168.0.39:8083`
- 2026-06-11 18:20 左右，用户已确认在开发者工具中用 `http://127.0.0.1:8083` 点击“保存”成功。

### 10. 后端 RFID 注册已持久化

文件：

```text
backend/app/store.py
backend/app/config.py
```

已完成：

- RFID 用户注册不再只保存在内存，当前会持久化到本机 `backend/data/rfid_users.json`。
- 后端重启后会自动加载已登记 UID，因此真实卡 `436A4B07` 不需要每次重启后都重新注册。
- 未注册卡扫描时会清空 `current_user/mode`，避免界面继续显示上一次授权用户。
- `backend/tests/` 已补齐仓库根目录可直接运行的导入配置，并新增 RFID 持久化回归测试。

### 11. 2026-06-11 晚间已验证“重启后端 -> 自动回连 -> 模拟刷真实卡 UID”

本轮为验证 RFID 持久化是否真正落到运行中的新后端，已额外完成：

- 停掉旧的 8083 后端进程并用最新代码重新启动。
- 确认 ESP32S3 会话自动回连，状态恢复为：

```text
connection_count=1
online=true
uart_ok=true
session_connected=true
```

- 通过 HTTP 将真实卡 UID `436A4B07` 重新登记为 `student/study`，并确认其已写入：

```text
backend/data/rfid_users.json
```

- 随后直接调用 `POST /api/rfid/scan` 模拟刷卡，观察到最新后端会话下发：

```text
NET:CMD:<tts_id>:NET:TTSHEX:[...]
NET:CMD:<oled_id>:NET:OLED:STUDY MODE
NET:CMD:<lock_id>:NET:LOCK:OFF
```

- STM32 已返回三条 ACK，最新诊断为：

```text
last_rfid_uid=436A4B07
last_rfid_authorized=true
current_user=student/study
ack_ok_count=3
ack_err_count=0
pending_action_count=0
last_ack action=act_d6bffb101da0 OK
```

说明：

- 这里的 `ack_ok_count=3` 是因为本次验证前重启了后端；该计数是运行时内存态统计，重启后会从 0 重新累计，这属于预期行为，不代表闭环退化。

### 12. Web 控制台真实语音入口已落地

文件：

```text
backend/app/main.py
backend/app/schemas.py
backend/app/static/console.html
```

已完成：

- 新增 `POST /api/asr/recognized`，用于接收“客户端已经真实识别出的文本”，并写入 `last_asr_text` 后复用现有 AI/TTS/ACK 主链路。
- Web 控制台已新增“开始语音”按钮，使用浏览器原生 `SpeechRecognition / webkitSpeechRecognition` 做中文识别。
- 浏览器识别出的文本会直接进入后端，再生成：

```text
NET:CMD:<tts_id>:NET:TTSHEX:<utf8_hex>
NET:CMD:<oled_id>:NET:OLED:...
NET:CMD:<fan_id>:NET:FAN:ON:2
```

- 已在最新后端进程上实测调用：

```text
POST /api/asr/recognized text=打开风扇 source=browser_speech
```

- STM32 已对这一轮返回：

```text
BT:ACK:<tts_id>:OK
BT:ACK:<oled_id>:OK
BT:ACK:<fan_id>:OK
```

实测结果：

```text
last_text=打开风扇
last_asr_text=打开风扇
last_assistant=已准备打开风扇二档。
ack_err_count=0
pending_action_count=0
```

使用说明：

- 当前“真实语音”是通过 Web 控制台浏览器麦克风完成，推荐使用 Chrome/Edge。
- 这一步已经满足“真人说话 -> 真识别 -> AI 回复 -> 真播报/真控制”的答辩演示需求。
- 但它还不等同于“ESP32S3 板载麦克风已完成采音上传”；后者仍是下一阶段增强项。

### 13. STM32 真实传感器 telemetry 已刷机并进后端

文件：

```text
firmware/stm32/stm32_executor/stm32_executor.ino
backend/app/static/console.html
miniprogram/pages/index/index.js
miniprogram/pages/index/index.wxml
```

已完成：

- STM32 新增周期性 `BT:{...}` telemetry，上报频率约 4 秒。
- 当前固件会采样：
  - `PA5` 电位器原始值 `pot_raw`
  - `AHT20` 温度 `temperature_c`
  - `AHT20` 湿度 `humidity_pct`
  - 超声波状态 `distance_ok`，若成功则附带 `distance_cm`
- 新增调试命令：

```text
NET:TELEMETRY?
```

- Web 控制台和小程序首页已新增传感器指标展示位：温度、湿度、距离、电位器。

已实机编译/刷录：

```powershell
arduino-cli compile --fqbn STMicroelectronics:stm32:GenF1:pnum=BLUEPILL_F103C8 --build-path .tmp\build-stm32 firmware\stm32\stm32_executor
openocd.exe -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program .tmp/build-stm32/stm32_executor.ino.elf verify reset exit"
```

刷录后后端已收到最新传感器状态：

```text
pot_raw=561
aht20_ok=true
temperature_c=26.4
humidity_pct=62
distance_ok=false
```

说明：

- 这意味着当前已实机打通 AHT20 与电位器数据进入后端。
- 超声波代码路径已接入 telemetry，但本轮刷机后该设备暂未返回有效距离，后续优先检查探头朝向、供电或接线。
- 这些传感器数据用于丰富 AI 对话上下文和设备状态展示，不应替代“智能对话”主线。

### 14. 本地对话能力已增强为“状态感知 + 组合意图”

文件：

```text
backend/app/ai.py
backend/tests/test_phase1.py
```

已完成：

- 本地规则对话不再只支持少量固定词，而是新增：
  - 设备状态问答：如“现在状态怎么样”
  - 传感器问答：如“现在温度多少”“距离多少”
  - 用户/模式问答：如“当前用户是谁”“现在什么模式”
  - 能力说明：如“你能做什么”
  - 组合意图：如“打开风扇并进入专注30分钟”
- 回复内容会结合实时 `sensors`、`online`、`uart_ok`、`session_connected`、`current_user`、`mode` 组织，而不是只回固定模板。

已测试：

```text
python -m pytest backend/tests -q
17 passed
```

已在最新后端 + 实机链路上验证：

1. 状态问答：

```text
POST /api/chat text=现在状态怎么样
```

返回示例：

```text
当前设备在线。实时会话已连接。串口链路正常。温度 26.3 度，湿度 62.6%。距离数据暂时不可用。电位器原始值是 561。
```

并已收到：

```text
BT:ACK:<tts_id>:OK
BT:ACK:<oled_id>:OK
```

2. 组合意图：

```text
POST /api/chat text=打开风扇并进入专注30分钟
```

生成并 ACK 成功：

```text
NET:CMD:<tts_id>:NET:TTSHEX:[...]
NET:CMD:<oled_id>:NET:OLED:FOCUS MODE
NET:CMD:<fan_id>:NET:FAN:ON:2
NET:CMD:<focus_id>:NET:OLED:FOCUS 30 MIN
```

说明：

- 这一轮增强已经让“智能对话”从单条关键词触发，升级到“基于当前设备状态回答 + 一句话拆分多个动作”。

### 15. 多轮对话记忆已接入后端状态

文件：

```text
backend/app/schemas.py
backend/app/store.py
backend/app/main.py
backend/app/ai.py
```

已完成：

- `DeviceSnapshot` 新增 `recent_dialogue`，会保留最近 12 条 `user/assistant` 对话。
- 所有文本入口都会共享这份上下文：
  - Web 文本 `POST /api/chat`
  - 浏览器真实语音 `POST /api/asr/recognized`
  - 其它后续复用 `run_text_turn(...)` 的入口
- 云端模型模式下，最近多轮对话和设备实时状态会一起进入 system/context prompt。
- 本地 mock 规则也已能利用最近对话完成简单“记忆型”问答。

新增可用问法示例：

```text
现在状态怎么样
你记得我刚才说了什么吗
现在适合学习吗
刚才执行了什么
你能做什么
```

已测试：

```text
python -m pytest backend/tests -q
19 passed
```

已在最新后端 + 实机链路上验证连续三轮：

1. `现在状态怎么样`
2. `你记得我刚才说了什么吗`
3. `现在适合学习吗`

结果：

- 第二轮会正确回复上一句 `现在状态怎么样`
- 第三轮会结合实时温湿度给出“适不适合学习”的建议
- 三轮对应的 `TTS/OLED` 动作均收到 STM32 `ACK`
- 当前状态可直接看到 `recent_dialogue` 已记录最近用户与助手多轮文本

## 最新实机验证结果

ESP32S3 已重新配置到测试后端：

```powershell
python tools\configure_esp32.py --port COM8 --server http://192.168.0.39:8083
```

后端状态：

```text
connection_count=1
online=true
uart_ok=true
session_connected=true
pending_action_count=0
```

UART keepalive 实测：

```text
[STM32 TX] NET:UART?
[STM32 RX] BT:PONG:<uptime_ms>
[STM32 RX] BT:OK
```

完整“打开风扇”闭环实测：

```text
[STM32 TX] NET:UART?
[STM32 TX] NET:CMD:<tts_id>:NET:TTSHEX:[30 bytes]
[STM32 TX] NET:CMD:<oled_id>:NET:OLED:FAN ON
[STM32 TX] NET:CMD:<fan_id>:NET:FAN:ON:2
[STM32 RX] BT:PONG:<uptime_ms>
[STM32 RX] BT:ACK:<tts_id>:OK
[STM32 RX] BT:ACK:<oled_id>:OK
[STM32 RX] BT:ACK:<fan_id>:OK
```

后端诊断最新结果：

```text
uart_ok=true
ack_ok_count=24
ack_err_count=0
pending_action_count=0
latest last_ack action=act_e3b8b865cde0 OK
```

RFID 模拟扫描后的追加结果：

```text
scan_authorized=true
ack_ok_count=27
ack_err_count=0
pending_action_count=0
latest last_ack action=act_8a1d283fbfec OK
```

RFID 真实卡追加结果：

```text
uid=436A4B07
authorized=true
current_user=student/study
ack_ok_count=28
ack_err_count=0
pending_action_count=0
latest last_ack action=act_0a8a1229b13c OK
```

## 当前可接受风险

- PB3 软件串口返回链路仍可能偶发首字节脏前缀，但现在 ESP32S3 会清洗，keepalive 也会持续刷新 UART 状态。
- SYN6288 协议 ACK 和人工听测均已成功；后续只需在展示前确认音量和清晰度。
- RFID 的后端模拟闭环和 RC522 真实卡闭环均已成功；当前默认会把已注册 UID 持久化到 `backend/data/rfid_users.json`，如手动删除该文件才需要重新注册 UID `436A4B07`。
- 当前已实机看到 `pot_raw`、`temperature_c`、`humidity_pct` 进入后端；`distance_ok=false` 说明超声波仍需补查，但不影响 AHT20 与电位器作为答辩时可展示的实时传感数据。
- 后端 `/api/health` 现在会返回 `ai_provider`、`ai_model`、`cloud_ready`；如果 `cloud_ready=false`，硬件闭环仍可测，但真实云端 AI 需要确认后端进程正确读取 `.env`，不要在日志或文档中展开密钥。
- 已新增 `tools/cloud_dialogue_smoke.py`，用于现场三轮多轮对话冒烟测试；它只打印 provider/model/cloud_ready、回复片段、动作类型、ACK 计数，不会打印 API Key。脚本默认最多等待 10 秒，让 STM32 ACK 回传后再汇总；默认即使 `cloud_ready=false` 也只提示不报错，答辩前强制云端验收可加 `--require-cloud`。
- 已修复长中文 TTSHEX 的落地风险：后端现在按 UTF-8 字节截断 SYN6288 播报 payload，保留 180 字节安全上限，避免云端/多轮回复过长导致 STM32 `BT:ACK:<id>:ERR`。
- 开发者工具模拟器在当前电脑上可能继续受 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` 影响；如果再次出现 `HTTP 502`，优先尝试关闭代理/VPN、重启开发者工具，并继续使用 `http://127.0.0.1:8083` 做模拟器联调。

## 新窗口建议开局

第一句话可以直接发：

```text
请先读取 docs/CURRENT_PROGRESS_HANDOFF.md、docs/PROTOCOL.md、docs/HARDWARE_WIRING.md。当前 STM32 已支持 NET:TTSHEX / SYN6288，用户已听到实际播报；ESP32S3 已加 UART keepalive、返回前缀清洗、RFID WUPA 唤醒和 ACK HTTP 回传；Web“打开风扇”到 STM32 ACK 已验证，RC522 真实卡 UID 436A4B07 已注册为 student/study 并完成 RFID 授权扫描到 STM32 ACK，小程序真实 AppID 已换成 wx7397c01ea9d04c21，微信开发者工具可直接打开仓库根目录且模拟器用 http://127.0.0.1:8083 保存后端地址已成功，最新 ack_ok_count=28、ack_err_count=0、pending_action_count=0。不要改动或泄露 backend/.env。
```

建议启动顺序：

1. 启动后端：

```powershell
cd "D:\HuaweiMoveData\Users\35267\Documents\New project2"
python tools\start_backend.py --bind-host 0.0.0.0 --health-host 127.0.0.1 --port 8083 --timeout 20
```

2. 监听 ESP32S3：

```powershell
python tools\serial_console.py COM8 --baud 115200 --monitor
```

3. 检查实时状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8083/api/realtime/status
Invoke-RestMethod http://127.0.0.1:8083/api/realtime/diagnostics/desktop-agent-001
```

4. 检查云端模型对话是否就绪：

```powershell
python tools\cloud_dialogue_smoke.py --base-url http://127.0.0.1:8083
```

期望看到 `cloud_ready=true`、`ai_provider=dashscope_openai`、`ai_model=qwen-plus`；如果是 `cloud_ready=false`，说明仍在本地规则兜底，不要宣称已经完成真实云端模型对话。

5. 重新测闭环：

```powershell
Invoke-RestMethod http://127.0.0.1:8083/api/chat -Method Post -ContentType 'application/json' -Body '{"device_id":"desktop-agent-001","text":"打开风扇"}'
```

6. 小程序联调要点：

```text
开发者工具模拟器填写 http://127.0.0.1:8083
真机预览/手机填写 http://192.168.0.39:8083
如果模拟器再报 HTTP 502，先检查是否开启了代理/VPN
```

## 下一步推荐

优先级建议：

1. 继续做小程序闭环：先在开发者工具模拟器完成“保存 -> 立即刷新 -> 打开风扇 -> RFID 注册/模拟刷卡”，再转真机预览，把后端地址切到 `http://192.168.0.39:8083`。
2. 演示前如果重启过后端，优先先检查 `backend/data/rfid_users.json` 仍在，再刷真实卡 UID `436A4B07` 验证 `last_rfid_authorized=true`；只有手动删掉持久化文件后才需要重新注册。
3. 如果后续又出现 ACK 丢失，再考虑逻辑分析仪抓 PB3/PB11，或者重新评估牺牲 `PA9` 使用 `USART1 PA9/PA10`。
4. 演示前准备一个固定脚本：启动后端、打开 COM8 monitor、开发者工具或手机小程序输入“打开风扇”、刷 RFID 卡、观察 OLED/FAN/TTS/RGB/ACK。

## 2026-06-11 20:35 云端真实对话验收补充

- 真实云端模型链路已跑通：`/api/health` 显示 `ai_provider=dashscope_openai`、`ai_model=qwen-plus`、`cloud_ready=true`。
- 强制云端冒烟已通过：`python tools\cloud_dialogue_smoke.py --base-url http://127.0.0.1:8083 --require-cloud --ack-wait-seconds 20`。
- 最近一次冒烟结果：`cloud_fallback_detected=false`、`device_online=true`、`uart_ok=true`、`session_connected=true`、`ack_ok_count=6`、`ack_err_count=0`、`pending_action_count=0`。
- 后端单元测试已通过：`python -m pytest backend\tests -q` -> `21 passed, 1 warning`。
- 已新增专用交接文件：`docs/CLOUD_DIALOGUE_HANDOFF.md`。
- 不要打印、提交或复制 `backend/.env` 内容；文档中只记录云端就绪状态，不记录任何 API Key。

## 2026-06-11 21:56 云端播报短句补充

- `backend/app/ai.py` 已要求云端 Qwen 输出结构化 `{"reply","speech"}`，其中 `reply` 面向 Web/小程序完整展示，`speech` 面向 SYN6288 做更短播报。
- `backend/app/store.py`、`backend/app/static/console.html`、`miniprogram/pages/index/*` 已补充最近播报短句展示，可直接用于答辩解释“显示文本”和“实际播报”分离。
- `tools/cloud_dialogue_smoke.py` 现在会在每轮输出中同时保留 `reply` / `speech` 片段，便于演示前确认播报文案长度。
- 最新后端单元测试结果：`python -m pytest backend\tests -q` -> `23 passed, 1 warning`。

## 2026-06-11 22:12 通用大模型回答能力补充

- `backend/app/ai.py` 已把系统定位从“设备短答助手”放开为“通用智能助手 + 智能硬件能力”，复杂问题会由 Qwen 展开回答，简单硬件控制仍保持短答。
- 新闻类问题会先抓取公开 RSS 新闻条目，再把新闻上下文交给 Qwen 汇总；新闻源不可用时要求明确说明，不编造实时新闻。
- 已用复杂问题实测：完整 `reply` 约 615 字，`speech` 54 字节，硬件只播短句；STM32 回传 `ack_ok_count=2`、`ack_err_count=0`、`pending_action_count=0`。
- 最新后端单元测试结果：`python -m pytest backend\tests -q` -> `25 passed, 1 warning`。

## 2026-06-11 22:18 演示入口补充

- Web 控制台 `/console` 已显示云端模型状态，并新增“世界新闻 / 复杂解释 / 状态建议 / 组合动作”四个演示按钮。
- 小程序 AI 对话区已同步新增“世界新闻 / 复杂解释 / 状态建议”预设问题，方便手机端展示通用大模型回答能力。
- 控制台现在会在完整 `reply` 后额外显示 `speech` 播报短句，便于现场解释 Web 完整回答和 SYN6288 短播报分离。

## 2026-06-11 22:25 ESP32S3 硬件麦克风 ASR 决策

- 已新增阶段计划文档：`docs/ESP32_MIC_ASR_PHASE_PLAN.md`。
- 决策：保留浏览器 Web Speech API 作为答辩兜底入口，同时推进 ESP32S3 Sense 板载麦克风硬件语音入口。
- 下一阶段最小目标：ESP32S3 采集 3 秒短录音，封装 WAV/PCM，通过 HTTP 上传到后端 `/api/asr/transcribe`。
- 后端目标：把 `ASR_PROVIDER=dashscope_paraformer` 落成真实 Paraformer 识别；识别成功后复用现有 Qwen/STM32 ACK 主链路。
- 不建议当前直接做实时流式 ASR、唤醒词或 VAD；这些放到短录音闭环稳定之后。
