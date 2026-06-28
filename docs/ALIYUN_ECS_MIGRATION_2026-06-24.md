# 阿里云 ECS 迁移状态

更新时间：2026-06-24 21:55（北京时间）

## 当前结论

完整智能桌面 AI 终端后端已经迁移到阿里云 ECS：

```text
公网 HTTP：http://8.163.38.158
公网 HTTPS：https://8-163-38-158.sslip.io
ECS：华南 3（广州），Ubuntu 22.04
后端：FastAPI + Uvicorn 单 worker
反向代理：Nginx
服务：voice-iot.service
```

当前发布：

```text
/opt/smartdesk/releases/20260624T133850Z
```

当前回退：

```text
/root/rollback-smartdesk-20260624T133850Z.sh
```

## 已验证

- HTTP和HTTPS健康检查正常；
- WebSocket和WSS均完成 `hello -> ping -> pong`；
- DashScope Qwen真实对话成功，没有走本地兜底；
- `cloud_ready=true`；
- SQLite位于 `/var/lib/smartdesk/context.sqlite3`；
- `persistent_storage=true`；
- ESP32直连 `ws://8.163.38.158:80`；
- heartbeat和telemetry持续返回HTTP 200；
- 设备状态为 `online=true`、`uart_ok=true`、`session_connected=true`；
- `CFG:WS:WAKE` 经ECS下发STM32命令；
- STM32返回真实 `BT:ACK:<action_id>:OK`；
- ESP32通过WebSocket回传ACK；
- 最终 `ack_ok_count=2`、`ack_err_count=0`、`pending_action_count=0`；
- readiness检查为 `PASS`。

## 当前链路

```text
Web控制台 / 笔记本语音
  ↓ HTTPS / WSS
阿里云 ECS FastAPI
  ↓ WS + HTTP
ESP32S3
  ↓ UART
STM32 / 传感器 / RC522 / SYN6288 / 执行器
```

ESP32暂时使用HTTP/WS公网IP直连，因为临时 `sslip.io` 域名在ESP32端的DNS/TLS路径返回连接错误。电脑和浏览器端继续使用HTTPS/WSS。获得自有域名后再做ESP32 TLS证书链验收。

## 部署结构

```text
/opt/smartdesk/releases/<UTC timestamp>
/opt/smartdesk/current
/opt/smartdesk/venv
/var/lib/smartdesk
/etc/smartdesk.env
/etc/systemd/system/voice-iot.service
/etc/nginx/sites-available/voice-iot
```

部署工具：

```powershell
python .\deploy\aliyun-ecs\deploy_with_saved_secret.py
```

安全边界：

- `server_secret.local.json` 已被Git忽略；
- `backend/.env`、SQLite、用户数据和音频不进入发布包；
- 必要密钥经SSH加密连接写入 `/etc/smartdesk.env`；
- 密钥值不打印到终端或日志；
- Uvicorn保持单worker，避免内存设备状态和WebSocket跨进程分裂。

## 小程序边界

临时 `sslip.io` 域名不属于项目方，不适合作为微信正式合法域名。微信小程序正式迁移仍需：

- 自有域名；
- 中国大陆备案；
- HTTPS证书；
- 微信公众平台request合法域名配置；
- 重新上传体验版。

今晚答辩主链优先使用ECS Web控制台和笔记本语音入口；小程序保留原体验版作为备用展示。
