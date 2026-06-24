# 智能桌面 AI 终端｜答辩最终运行卡

更新时间：2026-06-24（北京时间）

## 当前正式主链

```text
Web 控制台 / 笔记本麦克风 / 微信开发者工具
                    ↓ HTTPS / WSS
阿里云 ECS FastAPI + DashScope Qwen
                    ↓ HTTP / WebSocket
ESP32S3
                    ↓ UART
STM32 + RC522 + 传感器 + OLED + SYN6288 + 执行器
                    ↓
带 action_id 的真实 ACK 返回 ECS
```

- Web 控制台：`https://8-163-38-158.sslip.io/console`
- ESP32：直连 `http://8.163.38.158` / `ws://8.163.38.158`
- Hugging Face：仅保留旧版本备份，不是当前答辩主链。
- 小程序源码默认指向 ECS HTTPS；开发者工具关闭域名校验时可联调。正式真机发布仍需要自有备案域名和微信合法域名配置。

## 上台前 10 分钟

1. 给 STM32、ESP32S3、传感器和执行器供电。
2. 确认电脑联网，COM7/COM8 没有被无关串口工具占用。
3. 双击：

```powershell
.\tools\start_defense_demo.cmd
```

4. 启动器必须出现：

```text
[relay] ESP32 is already connected directly to Aliyun ECS
[check] PASS
```

5. 浏览器打开控制台后，在安全设置中输入本次 `CONTROL_TOKEN`。口令只用于本次页面会话，不写入项目文件。
6. 若要使用笔记本语音，按提示启动麦克风前端；只展示网页时使用：

```powershell
.\tools\start_defense_demo.cmd -SkipVoice
```

## 两个验收命令

只读检查，不产生硬件动作：

```powershell
python .\tools\realtime_readiness_check.py
```

必须同时满足：

- `cloud_ready=true`
- `persistent_storage=true`
- `device_online=true`
- `websocket_session_connected=true`
- `uart_ok=true`
- `ack_errors_clear=true`
- `action_queue_clear=true`
- 状态与诊断时间不超过 20 秒
- 至少两项真实传感器字段

云端对话与 ACK 冒烟，会产生 TTS/OLED 等真实动作：

```powershell
python .\tools\cloud_dialogue_smoke.py --require-cloud
```

该脚本会从进程环境或本地 `backend/.env` 静默读取控制口令，只发送请求头，不打印口令。

## 5 分钟现场顺序

1. 展示 readiness `PASS`，证明不是旧快照。
2. 展示温湿度、电位器等实时变化。
3. 刷真实 RFID 卡，展示用户与模式切换。
4. 输入“打开风扇”，展示动作、实体执行和相同 action ID 的 ACK。
5. 输入“现在环境怎么样”，展示 AI 使用实时传感器上下文回答。
6. 使用笔记本麦克风说一句自然语言，展示 ASR → Qwen → TTS/OLED/执行器 → ACK。
7. 最后打开诊断页，展示 `ack_err_count=0`、`pending_action_count=0`。

## 现场降级顺序

1. 语音不稳：立即改用 Web 文本，保住 AI → 硬件 → ACK 主线。
2. RFID 偶发未读：移开卡片后重新靠近；模拟 UID 只能明确称为调试入口。
3. ESP32 公网直连暂时中断：启动器会启用本机 8091 relay 兜底。
4. 云模型不可用：明确说明当前进入本地规则降级，不把兜底称为云端 AI。
5. 小程序真机域名受限：改用微信开发者工具或 Web 控制台，不在现场修改网络和证书。

## 禁止现场临时改动

- 不修改 VPN、DNS、路由、防火墙或阿里云安全组。
- 不重新烧录固件，除非已有明确回退镜像和充足时间。
- 不展示或复制 `backend/.env`、服务器密码、API Key、控制口令。
- 不把 ESP32S3 板载麦克风描述为当前已验收入口。
- 不把“命令已发送”描述为“执行成功”；必须以 ACK 为准。

## 仍需人工完成的答辩材料

- 录制一段同版本完整成果视频。
- 制作 PPT/PDF 离线副本。
- 保存 readiness PASS、RFID 用户、传感器、动作 ID/ACK 四类截图。
- 至少完整计时彩排两遍。
- 正式小程序发布：购买自有域名、完成中国大陆备案、配置证书和微信合法域名。这是外部资质流程，不属于今晚可由代码替代的工作。
