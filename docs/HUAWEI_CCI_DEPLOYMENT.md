# 华为云 CCI 云平台部署

目标：不购买和管理云服务器，把当前 FastAPI + WebSocket 后端作为容器运行在华为云 CCI。

## 推荐路线

```text
GitHub 仓库 / Dockerfile
  -> 华为云 CodeArts Build 或 SWR 源码构建
  -> SWR 镜像仓库
  -> CCI 云容器实例
  -> 公网 HTTP/WS 临时验证
  -> 域名 + HTTPS/WSS + 小程序合法域名
```

## 资源

- SWR：保存容器镜像。
- CodeArts Build 或 SWR 源码构建：云端构建 Docker 镜像，避免本机安装 Docker。
- CCI：运行常驻 FastAPI 容器，支持 WebSocket 长连接。
- APIG 或公网 LoadBalancer：对外暴露 HTTP/WS；正式小程序需要 HTTPS/WSS。

## CCI 运行配置

- 容器端口：`7860`
- CPU：`0.25 vCPU` 请求，`0.5 vCPU` 上限
- 内存：`512 MiB` 请求，`1 GiB` 上限
- 健康检查：`/api/health`

环境变量：

- `AI_PROVIDER=dashscope_openai`
- `AI_MODEL=qwen-plus`
- `AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
- `ASR_PROVIDER=dashscope_paraformer`
- `ASR_WS_URL=wss://dashscope.aliyuncs.com/api-ws/v1/inference`
- `ASR_MODEL=paraformer-realtime-v2`
- `DASHSCOPE_API_KEY`：放到 CCI Secret，不写进 YAML。
- `CONTROL_TOKEN`：放到 CCI Secret，不写进 YAML。

## 文件

- `deploy/huawei-cci/smartdesk-cci.yaml`：CCI/Kubernetes 工作负载和服务清单。
- `deploy/huawei-cci/secret.example.yaml`：Secret 示例，不要填真实值后提交。

## ESP32S3 切换

临时公网 IP 测试：

```text
CFG:SERVER:ws://<cci-public-ip-or-domain>
```

正式域名：

```text
CFG:SERVER:wss://<your-domain>
```

ESP32S3 会连接：

```text
/api/realtime/ws?device_id=desktop-agent-001&edge_id=esp32s3-sense-001
```

只有带真实 `edge_id=esp32s3-sense-001` 的连接才会被后端标记为设备 WebSocket 在线。

## 验证

```bash
curl http://<public-address>/api/health
curl http://<public-address>/api/state/desktop-agent-001
```

网页：

```text
http://<public-address>/console
```

看到 `cloud_ready=true` 后，再用 ESP32S3 发送 `CFG:SERVER:...` 切到云平台地址，并验证：

- `session_connected=true`
- `online=true`
- `uart_ok=true`
- 蜂鸣动作 ACK 返回 `status=acked`
