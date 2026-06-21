# 国内云 / 私有服务器 WebSocket 部署方案

目标：把临时 Hugging Face + 本机 relay + HTTP 轮询链路，替换成公网服务器上的 HTTPS/WSS 主链路。

## 推荐购买

优先买一台阿里云或腾讯云轻量应用服务器 / ECS：

- 地域：如果要微信小程序正式上线，优先中国大陆地域，并准备备案域名；如果只做快速演示，可先买中国香港地域免去备案等待。
- 系统：Ubuntu 22.04 LTS 或 24.04 LTS。
- 规格：2 vCPU / 2 GB RAM 起步足够当前 FastAPI + WebSocket + Caddy；预算宽松可选 2 vCPU / 4 GB。
- 带宽：至少 3 Mbps，演示和传感器控制够用；如果后续恢复音频上传，建议 5 Mbps 或更高。
- 安全组 / 防火墙：开放 22、80、443。不要开放后端容器端口 7860 到公网。

## 目标链路

```text
ESP32S3 ── wss://your-domain/api/realtime/ws ─┐
网页端  ── https://your-domain/console        ├── Caddy ── FastAPI:7860
小程序  ── wss://your-domain/api/realtime/ws ─┘
```

HTTP 接口仍保留用于健康检查、控制提交和兜底刷新，但实时状态应优先走 WebSocket。

## 服务器初始化

```bash
sudo apt-get update
sudo apt-get install -y git ca-certificates curl
curl -fsSL https://get.docker.com | sudo sh
sudo apt-get install -y docker-compose-plugin
sudo usermod -aG docker "$USER"
```

重新登录 SSH 后继续。

## 部署

```bash
git clone https://github.com/yanghao328427-arch/smart-desktop-ai-terminal.git
cd smart-desktop-ai-terminal
cp deploy/.env.server.example deploy/.env.server
nano deploy/.env.server
docker compose --env-file deploy/.env.server -f deploy/docker-compose.public.yml up -d --build
```

`deploy/.env.server` 必填：

- `SMARTDESK_SITE_ADDRESS`：域名，例如 `smartdesk.example.com`；仅临时 IP 测试可填 `:80`。
- `DASHSCOPE_API_KEY`：阿里云百炼 / DashScope API Key。
- `CONTROL_TOKEN`：自定义控制口令，不要用 DashScope Key。

## 验证

```bash
curl -s https://your-domain/api/health
curl -s https://your-domain/api/state/desktop-agent-001
```

网页打开：

```text
https://your-domain/console
```

如果 `SMARTDESK_SITE_ADDRESS=:80` 做 IP 临时测试，则使用：

```text
http://server-ip/console
```

## ESP32S3 切换到公网 WebSocket

通过串口发送：

```text
CFG:SERVER:wss://your-domain
```

临时 IP 测试可用：

```text
CFG:SERVER:ws://server-ip:80
```

保存后 ESP32S3 会连接：

```text
/api/realtime/ws?device_id=desktop-agent-001&edge_id=esp32s3-sense-001
```

只有带真实 `edge_id=esp32s3-sense-001` 的连接才会被后端标记为设备 WebSocket 在线。

## 小程序配置

开发阶段：把后端地址改成 `https://your-domain`，保存后页面会自动建立 WebSocket。

正式发布前：

- 微信公众平台后台添加 request 合法域名：`https://your-domain`
- 添加 socket 合法域名：`wss://your-domain`
- 域名需要 ICP 备案和有效 TLS 证书；中国香港 / 海外域名可能影响小程序正式版合规。

## 常用运维命令

```bash
docker compose --env-file deploy/.env.server -f deploy/docker-compose.public.yml ps
docker compose --env-file deploy/.env.server -f deploy/docker-compose.public.yml logs -f smartdesk
docker compose --env-file deploy/.env.server -f deploy/docker-compose.public.yml logs -f caddy
docker compose --env-file deploy/.env.server -f deploy/docker-compose.public.yml up -d --build
```
