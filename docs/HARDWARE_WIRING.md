# 硬件接线基线

本文件是重建后的接线真相来源。除非另写迁移说明，不再临时换线。

## STM32 学习板接口参考

来自随板资料图：

- OLED：I2C 地址 `0x7A`，`SCL=PB6`，`SDA=PB7`。
- 温湿度传感器：I2C 地址 `0x70`，`SCL=PB6`，`SDA=PB7`。
- 超声波测距：`TRIG=PA11`，`ECHO=PA10`。
- 循迹模块：检测引脚 `PB14`。
- DRV8833 电机驱动：`PWM1=PA0 / TIM2_CH1`，`PWM2=PA1 / TIM2_CH2`。
- 蓝牙口 USART3：`TX=PB10`，`RX=PB11`。
- USB 串口 USART2：`TX=PA2`，`RX=PA3`。
- RGB：蓝 `PA6`，绿 `PA7`，红 `PB0`。
- 蜂鸣器：`PB9`。
- 舵机接口：`PB8`。
- NTC 温度传感器：`PA4`。
- 电位器：`PA5`。
- 旋转编码器：`A=PA8`，`B=PA9`，按键 `PB15`。
- 学习板按键映射：`KEY1=PB12`、`KEY2=PB13`、旋转编码器按键 `PB15`。当前固件中 `KEY1` 短按切换 OLED 信息副屏、长按回主屏；`KEY2` 短按终止当前播报，长按进入电脑麦克风 PTT 录音、松开立即上传。
- 继电器输出：控制引脚 `PB5`，常闭 `COM1/常开` 端子按板载丝印接线。

## ESP32S3 Sense 到 STM32

注意：本节 ESP32S3 侧引脚沿用既有实物接线，不随 STM32 学习板原生引脚图调整。该图片只用于校正 STM32 板载/原生模块引脚。

| ESP32S3 Sense | STM32 | 方向 | 作用 |
| --- | --- | --- | --- |
| `D5 / GPIO6 / TX` | `PB11 / USART3_RX` | ESP32S3 -> STM32 | 下发 `NET:*` 命令 |
| `D7 / GPIO44 / RX` | `PB3 / software TX` | STM32 -> ESP32S3 | 返回 `BT:*` ACK/状态 |
| `GND` | `GND` | 双向 | 共地 |

串口参数：

- ESP32S3 -> STM32：`9600 8N1`。
- STM32 -> ESP32S3：`4800 8N1`。

## SYN6288 TTS

| SYN6288 | STM32 |
| --- | --- |
| `VCC` | `5V` |
| `GND` | `GND` |
| `RXD` | `PB10 / USART3_TX` |
| `TXD` | 暂不接 |
| `SPK+ / SPK-` | 喇叭 |

约束：

- SYN6288 负责文字转语音，不负责 MP3 原声播放。
- 当前以中文短句为主，必要时使用 GB2312/HEX 指令。
- `PA9` 不再用于 TTS，因为它与旋转编码器冲突。

## 2026-06-13 DRV8833 fan correction

The physical fan is connected through the Botelvdong DRV8833 motor-driver port:

- `DRV8833 PWM1 / IN1 = PA0 / TIM2_CH1`
- `DRV8833 PWM2 / IN2 = PA1 / TIM2_CH2`
- Current firmware drives fan ON with `PA1` PWM and `PA0` LOW; the earlier `PA0` PWM direction spun this fan in reverse.
- `NET:FAN:ON:<1-3>` maps to about 85%, 92%, and 100% PWM duty so a small fan can start reliably.
- `NET:FAN:OFF` and `NET:MOTOR:OFF` pull both DRV8833 inputs LOW.
- `PB5` is still the native relay output pin, but it is not the fan output in the current wiring.

## Passive buzzer

The passive buzzer uses the native `PB9` buzzer pin. Firmware supports a short alert tone through `NET:BEEP` and short non-blocking preset melodies through `NET:MUSIC:<SUCCESS|ALERT|SCALE|STARTUP|BIRTHDAY>`. `NET:MUSIC:STOP` stops the current melody.

## RC522 RFID

推荐由 ESP32S3 接 RC522，避免再占用 STM32 关键串口。

| RC522 | ESP32S3 Sense | 作用 |
| --- | --- | --- |
| `3V3` | `3V3` | 供电 |
| `GND` | `GND` | 共地 |
| `SCK` | `D8 / GPIO7` | SPI clock |
| `MISO` | `D9 / GPIO8` | SPI MISO |
| `MOSI` | `D10 / GPIO9` | SPI MOSI |
| `SDA / SS` | `D3 / GPIO4` | 片选 |
| `RST` | `D2 / GPIO3` | 复位 |
| `IRQ` | 不接 | MVP 不使用 |

## 禁止事项

- 不再把 ESP32S3 接到 STM32 `PA2/PA3`，那是 USB 调试口。
- 不再围绕 ESP8266 AT 链路做主线修补。
- 不用灯光单独判断链路健康，必须结合后端诊断和 ACK。

## 2026-06-13 传感器验收记录

- I2C 总线 `PB6/PB7` 实测可见 `0x38` 与 `0x3D`，对应 AHT20 与 OLED。
- HCSR04 超声波模块已接入 `TRIG=PA11`、`ECHO=PA10`。固件默认启用测距，遥测应报告 `distance_enabled=true`；只有实测成功后才应出现有效 `distance_cm`。
- DRV8833 已接入原生位 `PA0/PA1`。蜂鸣器原生脚是 `PB9`，此前把蜂鸣器写成 `PA1` 会导致无声且与 DRV8833 `PWM2` 冲突。当前固件启动时把 DRV8833 双输入保持低电平；深夜静音测试只允许 `NET:MOTOR:OFF`，不做正反转/调速动作。
- 舵机已接入 `PB8`，当前固件支持 `NET:SERVO:<0-180>`；深夜静音测试不主动发送舵机动作命令。
- 旋转编码器按学习板资料保留 `A=PA8`、`B=PA9`、按键 `PB15`，遥测字段为 `encoder_delta`、`encoder_position`、`encoder_button`。旋转只调 SYN6288 音量，每个卡点调整 10%，在 0%/100% 封顶且不循环；OLED 只显示音量百分比，不再播报当前音量。
- RGB 灯默认进入传感器状态模式：绿色心跳代表健康空闲，青色代表前方交互区/循迹高电平，黄色代表温湿度关注，红色代表过近或传感器需检查，蓝色代表等待首帧遥测。ESP32S3 连线不因该灯光语义变化而改变。
