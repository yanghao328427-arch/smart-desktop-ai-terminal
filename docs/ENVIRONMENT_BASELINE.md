# 环境与实物基线

更新时间：2026-06-10

## 已确认目标

- 项目目标：完整 AI 语音终端，而不是仅用于答辩的文字演示。
- 移动端目标：微信小程序优先；原生 App 暂不作为第一优先级。
- MVP 策略：允许先完成文本闭环，再接入语音闭环。
- RFID 角色：登录/解锁入口，同时用于用户模式识别。
- 舵机：可选，不进入第一优先级。
- `ttf` 释义：用户所说 `ttf` 指 SYN6288 TTS 语音合成模块。

## 已确认硬件

| 模块 | 型号/说明 | 当前角色 |
| --- | --- | --- |
| STM32 | STM32F103C8T6 学习板 | 感知与执行主控 |
| ESP32 | Seeed Studio XIAO ESP32S3 Sense | WiFi、语音入口、RFID、边缘桥接 |
| TTS | SYN6288 | 本地中文短句播报 |
| RFID | RC522 | 刷卡登录/解锁 |
| 显示 | OLED | 状态显示 |
| 传感器 | AHT20、超声波、声音传感器 | 环境感知 |
| 执行器 | RGB、蜂鸣器、继电器/风扇 | 反馈与控制 |
| 调试器 | ST-Link V2 | STM32 下载/调试 |

## 串口与调试端口

| 设备 | 端口 | 用途 |
| --- | --- | --- |
| STM32 USB 串口 | `COM7` | STM32 日志与手动命令调试 |
| ESP32S3 Sense | `COM8` | ESP32S3 烧录、日志、命令调试 |

## Wi-Fi

| 项 | 值 |
| --- | --- |
| SSID | `Tenda_2C7AD0` |
| 频段 | 2.4GHz 优先 |
| 密码 | 不写入 Markdown；仅写入本地未提交配置 |

本地配置建议：

```ini
WIFI_SSID=Tenda_2C7AD0
WIFI_PASSWORD=<local-only>
```

## 需要继续确认

- STM32 当前 Keil 工程是否能直接编译、下载。
- ST-Link 与 STM32 的 SWD 接线是否稳定。
- ESP32S3 到 STM32 的实际 TX/RX 接线是否与 `docs/HARDWARE_WIRING.md` 一致。
- RC522 是否最终接 ESP32S3，而不是 STM32。

