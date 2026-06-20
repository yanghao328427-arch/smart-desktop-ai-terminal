# 微信小程序路线

## 定位

微信小程序作为课程设计的移动应用端，用于满足“手机 App 或微信小程序”的应用层要求。

第一版不做复杂原生能力，只做稳定可演示的设备控制与状态展示。

## 页面规划

| 页面 | 作用 |
| --- | --- |
| 首页 | 设备在线状态、当前用户、锁定状态、温湿度 |
| AI 对话 | 输入问题、查看 AI 回复、查看语音播报状态 |
| 设备控制 | 风扇、蜂鸣器、OLED、TTS、锁定/解锁 |
| RFID 用户 | 注册卡片、查看用户模式 |
| 诊断/演示 | WebSocket、UART、ACK、ASR 状态 |

## API 依赖

| 页面 | 后端接口 |
| --- | --- |
| 首页 | `GET /api/state/{device_id}`、`GET /api/realtime/diagnostics/{device_id}` |
| AI 对话 | `POST /api/chat` |
| 设备控制 | `POST /api/chat`，用文本指令触发风扇、蜂鸣器、OLED、锁定/解锁 |
| RFID 用户 | `POST /api/rfid/register`、`POST /api/rfid/scan` |
| 诊断/演示 | `GET /api/realtime/status` |

## 当前最小实现

已生成 `miniprogram/`：

- 单页合并状态、AI 对话、设备控制、RFID 和诊断。
- 后端地址可在页面内保存，手机实测时改为电脑局域网 IP。
- 不保存 API Key，不直连 STM32 或 ESP32S3。

## 开发顺序

1. 先用后端 Web 页面完成 UI 和接口验证。
2. 再用微信开发者工具创建小程序项目。
3. 小程序只对接已经稳定的后端 API。
4. 答辩时手机展示小程序，电脑展示 Web 控制台和日志。

## 注意事项

- 小程序不保存 API Key。
- 小程序不直接连接 STM32 或 ESP32S3。
- 小程序只和后端通信。
- 若局域网调试，手机和电脑需在同一 Wi-Fi。
- 若微信开发者工具要求 HTTPS，先用本地调试模式或后续再做云部署。
