# 总体架构

## 四层结构

```text
应用层
  Web 控制台 / 移动端页面 / 答辩演示页

平台层
  FastAPI 后端 / 设备状态 / RFID 用户 / AI Agent / 工具调用 / 诊断

网络层
  ESP32S3 WiFi / WebSocket 实时会话 / UART 到 STM32 / 本地 USB 调试

感知与执行层
  STM32F103 / AHT20 / 超声波 / 声音传感器 / RC522 / OLED / RGB / 风扇 / 舵机 / SYN6288
```

## 主链路

```text
用户语音或 Web 文本
    |
    v
ESP32S3 Sense
    |
    | WebSocket /api/realtime/ws
    v
FastAPI 后端
    |
    | assistant + stm32/commands
    v
ESP32S3 UART bridge
    |
    | NET:CMD:<action_id>:NET:<command>
    v
STM32 执行器
    |
    | BT:ACK:<action_id>:OK
    v
ESP32S3 -> 后端 ACK
```

## 状态机

| 状态 | 含义 | RGB/OLED |
| --- | --- | --- |
| `offline` | 后端不可达或 WebSocket 断开 | 红色闪烁 |
| `idle` | 在线但未处于一轮对话 | 暗绿或常规待机 |
| `listen` | 用户可以说话 | 绿色快闪，OLED 显示 LISTEN |
| `recording` | ESP32S3 正在录音 | 绿色高频闪 |
| `think` | 后端 ASR/LLM/工具调用中 | 黄色 |
| `speak` | TTS 或语音输出中 | 黄色呼吸 |
| `error` | 链路、ASR、UART 或 ACK 出错 | 红色脉冲并显示原因 |

## 阶段目标

### Phase 0：合同固定

- 固定接线、协议、状态机和测试流程。
- 后端提供文本闭环和诊断接口。
- Web/移动页面能看到状态和发送命令。

### Phase 1：文本闭环

- Web 文本或 `/api/realtime/inject` 进入后端。
- 后端生成 AI 回复和 `NET:TTS`/`NET:OLED` 命令。
- ESP32S3 转发给 STM32。
- STM32 执行并 ACK。

### Phase 2：RFID 独立验收

- RC522 读 UID。
- 后端注册 UID 与用户模式。
- 刷卡切换学习/休息/演示/管理员模式。

### Phase 3：语音闭环

- 先使用稳定唤醒词。
- 唤醒后进入 `listen`。
- 上传固定短句音频并保存原始音频用于回放。
- ASR 成功后走同一文本闭环。

### Phase 4：答辩增强

- 历史记录图表。
- 设备状态时间线。
- 课程报告和 PPT。
- 成果视频演示脚本。

