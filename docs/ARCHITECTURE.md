# 总体架构

## 四层结构

```text
应用层
  Web 控制台 / 微信小程序 / 答辩演示页

平台层
  Hugging Face 部署的 FastAPI 后端 / 设备状态 / RFID 用户 / DashScope AI / 工具调用 / 诊断

网络层
  ESP32S3 Wi-Fi / 本机 HTTP relay / HTTPS 公网后端 / UART 到 STM32 / 本地 USB 调试

感知与执行层
  STM32F103 / AHT20 / 超声波 / 声音传感器 / RC522 / OLED / RGB / 风扇 / 舵机 / SYN6288
```

## 当前答辩部署主链路

```text
Web 控制台 / 微信小程序
    | HTTPS / WSS
    v
Hugging Face：FastAPI + DashScope AI + 实时状态 / 指令 / ACK
    ^                                        |
    | HTTPS（本机 relay 转发）                 | GET commands / POST ACK
    |                                        v
本机 ESP32 relay :8091  <--- Wi-Fi --->  ESP32S3 Sense  <--- UART --->  STM32 / 传感器 / 执行器
```

ESP32 当前通过 HTTP relay 上报 heartbeat、遥测与 ACK，并轮询待执行指令；因此 `session_connected=false` 不等于设备离线。网页和小程序都只读取 Hugging Face 的状态接口，展示的是同一台 `desktop-agent-001` 设备的云端快照。

## 双云分工与边界

| 服务 | 角色 | 是否为当前答辩主链必需 |
| --- | --- | --- |
| Hugging Face | 部署 FastAPI、调用 DashScope、提供 Web/小程序公网 API、保存实时状态与 ACK | 是 |
| 华为云 IoTDA | ESP32 的可选 MQTT 设备云接入：属性上报与平台命令 | 否，作为平台扩展并行运行 |
| 华为云 CCI | 未来可替换 Hugging Face 的容器部署方案 | 否，当前未启用 |

IoTDA 是 ESP32 的并行设备云通道，不是“ESP32 → IoTDA → Hugging Face → 页面”的串行中转站。若 IoTDA 不可用，只要 ESP32 → 本机 relay → Hugging Face 正常，当前答辩主链仍可完成；反之，IoTDA 的属性上报不能替代 Web、小程序和 AI 所需的 Hugging Face 后端。

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
