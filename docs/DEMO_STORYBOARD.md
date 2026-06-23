# 答辩演示脚本

## 一句话定位

这是一个基于 STM32F103C8T6、ESP32S3 Sense、RC522 RFID 和 SYN6288 的智能桌面 AI 对话终端，具备感知、联网、AI 决策、语音播报和硬件控制闭环。

## 主讲重点

- 核心亮点是“用户真实发出一句自然语言，系统理解后给出回复并驱动硬件”。
- 语音输入、RFID、传感器和小程序都服务于这个主线。
- 不要把演示讲成“播放预制录音”或“固定脚本回放”；固定短句只用于提高答辩稳定性，不改变其本质是实时智能对话。

答辩前先运行只读的实时就绪检查，确认 `cloud_ready=true`、ESP32 的 `online=true`、`uart_ok=true`、最近上报不超过 20 秒，并且至少有两项真实传感器字段。讲解时可以说：模型密钥只保存在云端 Secret，STM32、ESP32S3、小程序和网页端都拿不到密钥。

```powershell
python .\tools\realtime_readiness_check.py
```

检查脚本只读取 `/api/health`、`/api/state/{device_id}` 和 `/api/realtime/diagnostics/{device_id}`；它不发送聊天、动作或 ACK。输出 `"verdict": "PASS"` 后再开始正式演示。若为 `FAIL`，先查看 `failed_checks`，不要用旧快照冒充实时数据。

若被问到为什么同时接入 Hugging Face 与华为云，可直接说明：Hugging Face 是本次演示的应用云端主链，负责 AI、Web/小程序接口、状态和 ACK；华为云 IoTDA 是 ESP32 的并行 MQTT 设备云扩展，不是页面数据的中转站；华为云 CCI 只是答辩后的可选迁移方案。

## 一键启动整套答辩链路

使用以下任一方式启动：

```powershell
.\tools\start_defense_demo.cmd
# 或
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\start_defense_demo.ps1
```

启动器会按顺序：保留已运行的 relay（缺失时才启动一份）→ 等待只读 P0 自检通过 → 打开 Hugging Face 网页控制台 → 经确认后在独立窗口启动笔记本麦克风的持续语音监听。它不修改电脑网络、VPN、DNS、路由或防火墙，也不会自动发送聊天、硬件动作或 ACK。

- 默认语音模式是持续监听器，使用当前已验证的麦克风设备 `1`；用 `-InputDevice 9` 等参数可临时切换录音设备。
- 若想使用短窗口的“唤醒词 → 指令录音”流程，运行 `.\tools\start_defense_demo.cmd -VoiceMode wakeword`。
- 若只准备网页/小程序，运行 `.\tools\start_defense_demo.cmd -SkipVoice`。
- 若只想列出可用录音设备，运行 `.\tools\start_defense_demo.cmd -ListAudioDevices`。

语音前端是**笔记本麦克风临时入口**，启动前会明确提示录音行为；它不应被表述成 ESP32S3 板载麦克风已经完成验收。

## 演示流程

### 0. 开场自检（30 秒）

操作：

1. 保持 ESP32 已供电、本机 relay 已运行；不改电脑网络、VPN、DNS、路由或防火墙。
2. 若刚重新插入或重启 ESP32，先等待其完成 Wi-Fi 与 UART 保活启动（现场预留 1—3 分钟）；不要在刚上电时把暂时的 `uart_ok=false` 当作最终故障。
3. 运行 `python .\tools\realtime_readiness_check.py`。
4. 展示 `PASS`、云端模型、最近上报时间和传感器字段，然后打开 Web 控制台与微信体验版。

讲解点：

- 先证明“此刻有真实上报”，再展示界面，避免把历史缓存当作实时数据。
- 网页和小程序读取同一条 Hugging Face 云端状态链路；两端数值应同步变化。
- “30 秒自检”是脚本执行和判读时间；ESP32 刚上电的启动等待不计入这 30 秒。

### 1. 四层架构说明

展示 Web 控制台首页：

```text
感知层：STM32 + 传感器 + RFID + 执行器
网络层：ESP32S3 Wi-Fi + WebSocket + UART
平台层：FastAPI + Qwen + Paraformer + 状态/动作管理
应用层：Web 控制台 + 微信小程序
```

### 2. 刷卡登录/解锁

操作：

1. 设备启动后 OLED 显示 LOCKED。
2. 使用 RFID 卡刷卡。
3. Web/小程序显示当前用户与模式。

讲解点：

- RFID 不只是摆设，而是登录/解锁入口。
- 后端可将不同 UID 映射为学习、休息、演示或管理员模式。

### 3. AI 文本闭环

操作：

1. Web 或小程序输入“你是谁”。
2. 后端生成 AI 回复。
3. STM32/SYN6288 播报。
4. OLED 显示简短状态。

讲解点：

- 先证明平台层到执行层稳定闭环。
- AI 动作通过 `NET:CMD:<id>:NET:*` 下发，并通过 ACK 确认。
- 这里不是写死的回复播放，而是后端根据本轮输入即时生成回复。

### 4. 语音闭环

操作：

1. 打开 Web 控制台，点击“开始语音”。
2. 浏览器弹出麦克风权限时点击允许。
3. 直接说“你是谁”“现在状态怎么样”或“打开风扇”等自然语言。
4. Web 控制台显示识别文本，后端进入 AI/TTS/硬件动作闭环。
5. SYN6288 播报，OLED/风扇按命令执行，诊断页出现 ACK。

讲解点：

- 当前答辩版真实 ASR 入口由浏览器麦克风承担，保证演示稳定。
- 后端负责承接识别文本、AI 规划和动作下发。
- STM32 负责本地执行与 ACK，不保存密钥。
- 重点强调“真实语音识别后进入 AI”，而不是播放既定录音。

### 5. 设备控制

操作：

- 打开风扇。
- 蜂鸣器提示。
- OLED 显示“FOCUS MODE”。
- RGB 切换状态。

讲解点：

- AI 不只是聊天，还能调用工具。
- 感控闭环满足课程设计要求。

### 6. 诊断页

展示：

- ESP32S3 在线。
- STM32 UART 正常。
- 最近 ASR 文本。
- 最近 AI 回复。
- 最近下发命令。
- ACK 成功计数。

讲解点：

- 系统可定位问题，不再只看灯光猜状态。
- 工程化程度高，可维护。
