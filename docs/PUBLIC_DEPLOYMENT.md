# 公网部署说明

目标：网页端和小程序端访问同一个公网后端，状态和传感器数据继续来自真实后端/ESP32/STM32 链路，不使用演示假数据。

## 1. 推送仓库

当前本地仓库还没有配置 Git remote。先把本仓库推到 GitHub、GitLab 或 Bitbucket，再在 Render 导入。`.gitignore` 已经排除 `.env` 和 `backend/data/`，不要把本地密钥文件提交上去。

## 2. Render Blueprint

1. 打开 Render Blueprint 新建页：`https://dashboard.render.com/blueprint/new`。
2. 选择刚推送的仓库，Render 会读取根目录 `render.yaml`。
3. 在环境变量里填写：
   - `DASHSCOPE_API_KEY`：通义千问 / ASR 使用的 DashScope Key。
   - `CONTROL_TOKEN`：公网控制口令，网页和小程序写入类操作会带 `X-Demo-Token`。
4. 部署完成后确认：
   - `https://你的-render域名/api/health`
   - `https://你的-render域名/console`
   - `https://你的-render域名/mobile`

默认小程序端已指向：`https://smart-desktop-ai-terminal.onrender.com`。如果 Render 最终给的域名不同，需要在小程序“连接后端”里保存真实域名，或修改 `miniprogram/app.js` 的 `apiBase`。

## 3. 网页端公网使用

进入 `/console` 后，在左侧“控制口令”输入 Render 的 `CONTROL_TOKEN`。状态、诊断、传感器读取保持公开实时；控制、AI 对话、RFID 注册/扫描、ASR 上传需要口令。

## 4. 小程序公网使用

1. 小程序默认后端为 HTTPS Render 域名。
2. 首页“公网控制口令”填写同一个 `CONTROL_TOKEN` 并保存。
3. 微信公众平台后台需要把 Render 域名加入 request 合法域名，例如：`https://smart-desktop-ai-terminal.onrender.com`。
4. 如果 Render 域名变了，同时更新小程序后端地址和微信合法域名。

## 5. ESP32 接入公网后端

公网 Render 只提供 HTTPS/WSS。ESP32 固件已支持 `https://` / `wss://` 服务地址。刷入固件后，用串口配置实际公网地址：

```powershell
python tools/configure_esp32.py --port COM8 --server https://smart-desktop-ai-terminal.onrender.com
```

如果你的 Render 域名不同，把命令里的 URL 换成真实域名。配置后，ESP32 的心跳、遥测、WebSocket 闭环状态会回传到公网后端，网页和小程序才能看到真实实时数据。

## 6. 注意事项

- Render 免费实例会休眠，第一次打开可能冷启动几十秒。
- 免费实例本地文件是临时存储，RFID 注册表和上传录音在重启后可能丢失；要长期保存可升级 Render Disk 或改数据库。
- 设备侧接口暂时保持无口令，避免当前 ESP32/STM32 实时数据链路断开；公网环境请只在演示时开启服务，后续可给固件增加设备令牌。