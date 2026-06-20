# 已安装技能与项目应用方式

更新时间：2026-06-11

本文件记录为智能桌面 AI 终端项目新增安装的 Codex skills，以及它们在项目中的具体触发场景。安装位置为用户级技能目录：

```text
C:\Users\35267\.codex\skills
```

安装后建议重启 Codex，使新技能能被自动发现和触发。

## 已安装的 5 个技能

| Skill | 用途 | 本项目应用阶段 |
| --- | --- | --- |
| `playwright` | 用真实浏览器自动检查 Web 控制台、移动端页面和交互流程 | Phase 1、Phase 6、答辩前验收 |
| `transcribe` | 转写录音文件，辅助评估 ASR 质量和语音样本 | Phase 5 语音闭环 |
| `pdf` | 读取、创建、检查 PDF，处理课程任务书、报告导出和最终材料 | Phase 0、Phase 7 |
| `security-best-practices` | 检查 Python/JS Web 项目的密钥、接口、前后端安全默认值 | Phase 1、Phase 6、部署前 |
| `render-deploy` | 分析后端并生成 Render 部署方案或 `render.yaml` | 云端演示、手机远程访问 |

## 选择理由

### playwright

Web 控制台和移动端页面不能只靠“看起来能打开”。这个技能用于：

- 打开 `/console`、`/mobile`、`/docs`。
- 自动输入 AI 对话。
- 点击设备控制按钮。
- 截图记录页面状态。
- 检查页面在桌面和手机视口下是否有遮挡、空白、错位。

项目触发语句示例：

```text
使用 playwright 检查 Web 控制台和移动端页面，验证 AI 对话、设备控制和诊断页流程。
```

### transcribe

虽然最终 ASR 选择阿里云 Paraformer，但项目仍需要保存和人工评估 ESP32S3 上传的原始音频。这个技能用于：

- 对保存的 WAV 样本做离线转写对照。
- 判断问题在“录音质量”还是“ASR 接口”。
- 为答辩报告保留语音识别样本分析。

项目触发语句示例：

```text
使用 transcribe 检查 backend/data/audio_samples 下的测试录音，输出每条样本的识别结果和问题判断。
```

注意：如果不用 OpenAI 转写，只把它作为音频验收工作流参考即可；正式后端仍以 DashScope Paraformer 为主。

### pdf

课程任务书、报告和最终交付常常需要 PDF。这个技能用于：

- 读取任务书 PDF 或导出的报告 PDF。
- 检查报告导出后页面是否错位。
- 处理答辩材料中的 PDF 摘录。
- 对最终 PDF 做页数、文本、图片布局检查。

项目触发语句示例：

```text
使用 pdf 检查最终课程设计报告 PDF，确认页面渲染、目录、图片和表格没有错位。
```

### security-best-practices

本项目包含 Wi-Fi 密码、DashScope API Key、后端接口、小程序前端和设备控制接口。这个技能用于：

- 检查 `.env`、`.gitignore`、日志和文档，避免泄露密钥。
- 检查 FastAPI 接口是否有危险的未鉴权控制面。
- 检查小程序是否把密钥写到前端。
- 检查部署前的 CORS、日志、配置默认值。

项目触发语句示例：

```text
使用 security-best-practices 对 backend 和 miniprogram 做一次安全默认值检查，重点看密钥、CORS、设备控制接口和日志泄露。
```

### render-deploy

手机真机和小程序调试经常需要一个稳定公网后端。这个技能用于：

- 分析 FastAPI 后端部署要求。
- 生成 `render.yaml`。
- 明确环境变量配置方式。
- 给小程序提供 HTTPS 后端地址。

项目触发语句示例：

```text
使用 render-deploy 为 backend 生成 Render 部署方案和 render.yaml，不包含任何密钥明文。
```

## 阶段使用矩阵

| 阶段 | 主要技能 | 使用目标 |
| --- | --- | --- |
| Phase 1 后端文本闭环 | `security-best-practices` | 写安全默认值，保护 API Key 和设备控制接口 |
| Phase 1 页面验收 | `playwright` | 自动跑 Web 控制台和移动页交互 |
| Phase 5 语音闭环 | `transcribe` | 对照评估 ESP32S3 原始录音 |
| Phase 6 微信小程序 | `playwright`、`security-best-practices` | 检查手机视口页面和前端密钥安全 |
| Phase 7 答辩打包 | `pdf` | 检查最终 PDF 报告 |
| 云端演示 | `render-deploy`、`security-best-practices` | 生成部署配置并做部署前安全检查 |

## 使用注意

- 新技能安装后，重启 Codex 才能在技能列表中自动出现。
- 不要让 `speech` 或 `transcribe` 替代项目主线选型；本项目主线仍是 DashScope Qwen + Paraformer + SYN6288。
- 不要把 Wi-Fi 密码、DashScope API Key 写入任何技能输出文件。
- 部署技能只生成配置，不负责保存密钥；Render 环境变量应在平台控制台配置。

