# WakeNet 迁移前稳定基线

保存时间：2026-06-25（Asia/Shanghai）

这份基线是接入 ESP-SR WakeNet 前的可工作版本，保留以下能力：

- KEY2 通过 COM7 触发笔记本麦克风 PTT。
- ASR 使用云端 Paraformer。
- Qwen 回复经后端分句后发送到 STM32 SYN6288。
- ESP32 到 STM32 使用统一碎片协议、action-id ACK 与重试。
- 当前唤醒词静音测试仍使用笔记本 ASR 文本匹配。

## 后端

当前部署发布号：

```text
20260624T190511Z
```

服务端回退脚本：

```text
/root/rollback-smartdesk-20260624T190511Z.sh
```

## STM32 回刷

稳定固件保存在：

```text
.tmp/rollback-wakenet-baseline-20260625/stm32/
```

回刷命令：

```powershell
openocd.exe -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program .tmp/rollback-wakenet-baseline-20260625/stm32/stm32_executor.ino.elf verify reset exit"
```

## ESP32S3 回刷

稳定固件保存在：

```text
.tmp/rollback-wakenet-baseline-20260625/esp32/
```

最快二进制回刷：

```powershell
python -m esptool --chip esp32s3 --port COM8 --baud 460800 write_flash --flash_mode dio --flash_freq 80m --flash_size 8MB 0x0 .tmp\rollback-wakenet-baseline-20260625\esp32\main.ino.bootloader.bin 0x8000 .tmp\rollback-wakenet-baseline-20260625\esp32\main.ino.partitions.bin 0x10000 .tmp\rollback-wakenet-baseline-20260625\esp32\main.ino.bin
```

源码回刷：

```powershell
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
arduino-cli upload -p COM8 --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
```

## 回退文件校验

```text
ESP32 main.ino.bin             E930E02EE5644130C937A189B54005F47CE6B42324D86AEBDA18A7C3594D8F9F
ESP32 main.ino.bootloader.bin  1776E4DD896A69D0A5C2E79957B0E2A88AA4129B1381D6478683515A1F6AF343
ESP32 main.ino.partitions.bin  1D9CCA96DE0FE07AD7FC0648B9878DDECD9CE565E38B589AD20FEA698ED4C80C
STM32 stm32_executor.ino.elf   4E7FC277A7683FB54B0D1D201F75193446F3514276A6F1D02BF31E893420A2D4
```

需要重新确认时：

```powershell
Get-ChildItem -File -Recurse .tmp\rollback-wakenet-baseline-20260625 | Get-FileHash -Algorithm SHA256
```

## 基线验收

保存前已完成：

- 后端测试：70 passed。
- STM32 编译和 Flash verify：通过。
- ESP32 编译、上传和 Hash verify：通过。
- 同一录音回放：ASR 识别“你喜欢梅西还是C罗？”。
- STM32 两段 TTS：82B 与 27B 均返回 ACK OK。
- 静音唤醒正样本：“灵宝灵宝”“你好灵宝”命中。
- 静音负样本：“淘宝淘宝”“林宝宝宝”和普通问句不命中。

WakeNet 新实现必须放在独立目录中。在完成编译、刷写和硬件验收前，不删除或覆盖当前 Arduino 固件。

## 官方 WakeNet 探针状态

隔离工程：

```text
edge/esp32s3_wakenet_probe/
```

已完成：

- ESP-IDF 5.5.3 + ESP-SR 2.4.6 编译通过。
- 官方模型 `wn9_nihaoxiaoxin_tts` 已打包进 model 分区。
- 探针固件仅负责板载 PDM 麦克风和 WakeNet 检测，不接管现有云端闭环。

尚未执行：

- 探针没有刷入设备。
- “我在”播报、KEY2 优先、TTS 屏蔽和笔记本录音触发尚未宣称硬件验收通过。

明天受控测试时，先记录当前串口号。探针刷写后若不能稳定识别“你好小鑫”，或出现误唤醒，立即停止测试并按上面的 ESP32S3 回刷命令恢复稳定 Arduino 固件。
