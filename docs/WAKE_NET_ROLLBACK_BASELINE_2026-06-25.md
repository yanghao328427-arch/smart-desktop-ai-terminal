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

推荐源码回刷：

```powershell
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
arduino-cli upload -p COM8 --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
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
