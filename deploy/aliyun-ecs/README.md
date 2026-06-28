# 阿里云 ECS 迁移

本目录将当前完整 `backend/app` 部署到阿里云 ECS，不创建第二套 API。

## 安全边界

- 不读取或上传本地 `backend/.env`。
- 不打包 `backend/data`、音频、SQLite 或用户数据。
- SSH 密码只在系统 `ssh/scp` 提示中手动输入。
- 远端保持单 Uvicorn worker，避免内存设备状态和 WebSocket 被拆到不同进程。

## 执行

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\aliyun-ecs\deploy_interactive.ps1
```

如果已经填写被 Git 忽略的 `server_secret.local.json`，可以使用非交互部署：

```powershell
python .\deploy\aliyun-ecs\deploy_with_saved_secret.py
```

本机需要安装 `paramiko`。密码不会进入命令行或输出。

远端部署结构：

```text
/opt/smartdesk/releases/<timestamp>
/opt/smartdesk/current
/opt/smartdesk/venv
/var/lib/smartdesk
/etc/smartdesk.env
```

部署脚本会备份现有 `voice-iot.service`、Nginx 配置和旧 `main.py`，并输出对应回退脚本路径。

## 部署后

首次没有旧服务器 `.env` 时，系统以本地规则模式启动。需要在服务器上编辑：

```bash
nano /etc/smartdesk.env
```

增加：

```text
AI_PROVIDER=dashscope_openai
DASHSCOPE_API_KEY=<server-only secret>
```

随后：

```bash
systemctl restart voice-iot
curl http://127.0.0.1/api/health
```

不要把 `/etc/smartdesk.env` 下载或提交到仓库。
