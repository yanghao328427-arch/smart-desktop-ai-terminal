# 通信协议 v1

## WebSocket

入口：

```text
WS /api/realtime/ws?device_id=desktop-agent-001&edge_id=esp32s3-sense-001
```

连接后服务端发送：

```json
{"type":"hello","protocol":"smart-desktop-realtime-v1","device_id":"desktop-agent-001","edge_id":"esp32s3-sense-001"}
```

设备可发送：

```json
{"type":"wake"}
{"type":"text","text":"你是谁"}
{"type":"tools/list"}
{"type":"tools/call","name":"fan_control","arguments":{"state":"on","speed":70}}
{"type":"button","line":"BT:BTN:KEY2:DOWN","source":"stm32"}
{"type":"ping"}
```

服务端可返回：

```json
{"type":"state","state":"listen"}
{"type":"speak","text":"请说话"}
{"type":"state","state":"think","stage":"agent"}
{"type":"assistant","text":"...","speech":"..."}
{"type":"stm32/commands","lines":["NET:CMD:<id>:NET:TTS:..."]}
{"type":"button","line":"BT:BTN:KEY2:HOLD_START:650","source":"stm32"}
{"type":"interrupt","reason":"KEY2:DOWN"}
{"type":"state","state":"idle"}
```

## 后端 HTTP

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/health` | 服务健康检查 |
| `GET` | `/api/state/{device_id}` | 设备状态 |
| `POST` | `/api/hardware/telemetry` | STM32/ESP32 上传传感器状态 |
| `POST` | `/api/hardware/heartbeat` | ESP32S3 上传在线与 UART 状态 |
| `GET` | `/api/hardware/commands/{device_id}` | 旧式轮询调试命令 |
| `POST` | `/api/hardware/ack` | 确认动作执行 |
| `POST` | `/api/hardware/button` | ESP32S3 备用上报 STM32 `BT:BTN:*` 按钮事件 |
| `GET` | `/api/users` | 列出 SQLite 中的 RFID 用户；需要 `X-Demo-Token` |
| `POST` | `/api/users` | 创建无卡用户上下文；需要 `X-Demo-Token` |
| `POST` | `/api/context/select` | 控制口令切换到指定用户上下文；需要 `X-Demo-Token` |
| `POST` | `/api/rfid/enroll/start` | 发起在线注册，等待下一次真实 RC522 刷卡完成绑定；需要 `X-Demo-Token` |
| `GET` | `/api/rfid/enroll/{enroll_id}` | 查询在线注册状态；需要 `X-Demo-Token` |
| `POST` | `/api/rfid/register` | 手动 UID 备选绑定；需要 `X-Demo-Token` |
| `POST` | `/api/rfid/scan` | RFID 刷卡登录/解锁；网页模拟用 `X-Demo-Token` + `source=web_simulator`，真实 RC522 用 `X-Device-Token` + `source=rc522` |
| `POST` | `/api/chat` | Web/移动端文本对话；需要已注册卡上下文或 `X-Demo-Token` |
| `POST` | `/api/asr/transcribe` | 短音频上传与 ASR 识别，支持 mock 文本注入闭环 |
| `POST` | `/api/realtime/inject` | 后端注入实时会话 |
| `GET` | `/api/realtime/status` | 实时会话总览 |
| `GET` | `/api/realtime/diagnostics/{device_id}` | 分层诊断 |

`/api/health` 会返回当前 AI 模式：

```json
{
  "status": "ok",
  "protocol": "smart-desktop-realtime-v1",
  "ai_provider": "dashscope_openai",
  "ai_model": "qwen-plus",
  "cloud_ready": true,
  "device_id": "desktop-agent-001",
  "edge_id": "esp32s3-sense-001"
}
```

说明：`cloud_ready=true` 只表示后端已读取到云端模型配置并会走 DashScope 兼容接口；接口不会返回 API Key。

## STM32 短命令

生产下发使用包装命令：

```text
NET:CMD:<action_id>:NET:TTSHEX:<utf8_hex>
NET:CMD:<action_id>:NET:TTS:<text>
NET:CMD:<action_id>:NET:TTS:STOP
NET:CMD:<action_id>:NET:VOLUME:<0-16|UP|DOWN>
NET:CMD:<action_id>:NET:OLED:<text>
NET:CMD:<action_id>:NET:UI:USER:<user_id>:<uid>:<mode>
NET:CMD:<action_id>:NET:FAN:ON:2
NET:CMD:<action_id>:NET:BEEP
NET:CMD:<action_id>:NET:MUSIC:SUCCESS
NET:CMD:<action_id>:NET:MUSIC:STOP
NET:CMD:<action_id>:NET:SERVO:<0-180>
NET:CMD:<action_id>:NET:ULTRASONIC:ON
NET:CMD:<action_id>:NET:ULTRASONIC:OFF
NET:CMD:<action_id>:NET:MOTOR:OFF
NET:CMD:<action_id>:NET:RGB:STATUS?
NET:CMD:<action_id>:NET:RGB:LEGEND?
NET:CMD:<action_id>:NET:RGB:MODE:SENSOR
NET:CMD:<action_id>:NET:RGB:MODE:EVENT
NET:CMD:<action_id>:NET:LOCK:ON
NET:CMD:<action_id>:NET:LOCK:OFF
NET:CMD:<action_id>:NET:AI:BUSY
NET:CMD:<action_id>:NET:AI:IDLE
```

STM32 执行后返回：

```text
BT:ACK:<action_id>:OK
BT:ACK:<action_id>:ERR
BT:PONG:<uptime_ms>
BT:{"pot_raw":561,"pot_pct":54,"ntc_raw":1017,"ntc_pct":99,"tracking_signal":false,"aht20_ok":true,"temperature_c":26.4,"humidity_pct":62.0,"distance_ok":true,"distance_enabled":true,"distance_cm":31.4,"distance_zone":"near","env_state":"comfortable","interaction_hint":"object_near","rgb_mode":"sensor","rgb_status":"near_object","rgb_reason":"interaction_zone","encoder_delta":0,"encoder_position":0,"encoder_button":false}
BT:RGB:mode=sensor,status=near_object,reason=interaction_zone,env=comfortable,distance=near,pot_pct=55,ntc_pct=99,tracking=1
BT:BTN:KEY1:PAGE:<screen_index>
BT:BTN:KEY1:HOME
BT:BTN:KEY2:DOWN
BT:BTN:KEY2:HOLD_START:<duration_ms>
BT:BTN:KEY2:UP:<duration_ms>
BT:BTN:KEY2:SHORT:<duration_ms>
BT:LOCK:ON
BT:LOCK:OFF
```

按钮语义：`KEY1/PB12` 在 OLED 主状态和信息副屏之间切换，长按回主屏；`KEY2/PB13` 按下即打断当前播报，超过约 600ms 后进入电脑麦克风 PTT 录音，松开立即上传。

调试时仍允许直接发：

```text
NET:TTS:你好
NET:TTS:STOP
NET:OLED:AI READY
NET:FAN:OFF
NET:MUSIC:SUCCESS
NET:MUSIC:ALERT
NET:MUSIC:SCALE
NET:MUSIC:STARTUP
NET:MUSIC:BIRTHDAY
NET:MUSIC:STOP
NET:UI:LISTEN
NET:UI:THINK
NET:UI:ACTION
NET:UI:ACK
NET:UI:IDLE
NET:UI:ERROR
NET:UI:USER:user_123:04A1B2C3:STUDY
NET:UART?
NET:TELEMETRY?
NET:ULTRASONIC:ON
NET:ULTRASONIC:OFF
NET:MOTOR:OFF
NET:SERVO:90
NET:RGB:STATUS?
NET:RGB:LEGEND?
NET:RGB:MODE:SENSOR
NET:RGB:MODE:EVENT
```

2026-06-13 native pin correction: buzzer is `PB9`; `PA1` is DRV8833 `PWM2`, so older `PA1` buzzer tests were checking the wrong pin. Relay output control is `PB5`, `KEY1` remains `PB12`, and `KEY2` remains `PB13`. Telemetry also includes `ntc_raw` from `PA4` and `tracking_signal` from `PB14`.

2026-06-13 DRV8833 fan routing correction: the physical fan is connected to the Botelvdong DRV8833 motor-driver port, not the `PB5` relay output. Current firmware routes `NET:FAN:ON:<1-3>` to `PA1/TIM2_CH2` PWM with `PA0/TIM2_CH1` held LOW, because the first PA0-PWM attempt spun this fan in the wrong direction. `NET:FAN:OFF` pulls both DRV8833 inputs LOW.

RGB status lighting legend: green heartbeat means ready; cyan pulse means front-object interaction zone or tracking high; yellow blink means environment watch; red fast/double blink means too close or sensor check; blue slow blink means waiting for first telemetry. Command/ACK colors still take priority briefly, then RGB returns to sensor-aware idle status.

2026-06-13 深夜静音验收记录：HCSR04 已接入，固件默认 `distance_enabled=true`；DRV8833 已接入 `PA0/PA1`，为避免发声或转动，当前只允许静音关断命令 `NET:MOTOR:OFF`，不在深夜测试正反转/调速；舵机命令保留但不主动发送。

## 动作映射

| Action type | STM32 命令 |
| --- | --- |
| `tts_speak` | `NET:TTSHEX:<utf8_hex>` |
| `audio_stop` | `NET:TTS:STOP` |
| `volume_control` | `NET:VOLUME:<0-16|UP|DOWN>` |
| `oled_display` | `NET:OLED:<text>` |
| `user_context` | `NET:UI:USER:<user_id>:<uid>:<mode>` |
| `fan_control` | `NET:FAN:ON:<1-3>` 或 `NET:FAN:OFF` |
| `buzzer_alert` | `NET:BEEP` |
| `buzzer_music` | `NET:MUSIC:<SUCCESS/ALERT/SCALE/STARTUP/BIRTHDAY/STOP>` |
| `focus_mode` | `NET:OLED:FOCUS <min> MIN` |
| `servo_action` | `NET:SERVO:<0-180>` |
| `lock_control` | `NET:LOCK:ON/OFF` |
| `lamp_control` | `NET:AI:<IDLE/BUSY/OFF>` |
