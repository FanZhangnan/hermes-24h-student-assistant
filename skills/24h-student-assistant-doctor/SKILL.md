---
name: 24h-student-assistant-doctor
description: 在不暴露凭证的前提下，诊断 24h 留学助理 Hermes Profile 的版本、配置、Gateway、Cron、模型路由、Vision、本地 API 边界、数据库和消息投递。
version: 0.1.0
platforms: [linux, macos, windows]
---

# 24h 留学助理诊断

先运行离线检查。macOS/Linux：

```bash
python3 "$HERMES_HOME/scripts/24h_assistant.py" doctor --json
```

Windows PowerShell：

```powershell
python "$env:HERMES_HOME/scripts/24h_assistant.py" doctor --json
```

逐项报告通过、警告、失败和修复建议。只能显示产品诊断器安全提取的当前模型提供商/模型名称。
绝不显示 `.env`、API 密钥、`API_SERVER_KEY`、平台令牌、私密日历 URL，也不显示原始 Hermes 状态或配置输出。
绝不运行 `hermes doctor --fix`，也不自动修改用户配置。

如果发现旧版 `provider_key` 警告，只建议迁移到 `key_env`；不得自行读取或移动密钥。在受限自动化
沙箱中出现的写入健康警告只能视为“无法判定”，不能作为用户真实 Hermes 数据库已损坏的证据。

## 消耗额度的检查

离线检查完成后，先说明模型验证会消耗 API 额度，Vision 验证会将自动生成的红色方块图片发送给已配置的
模型服务。每项检查都必须先取得用户的明确授权。

macOS/Linux：

```bash
python3 "$HERMES_HOME/scripts/24h_assistant.py" verify model
python3 "$HERMES_HOME/scripts/24h_assistant.py" verify vision
```

Windows PowerShell：

```powershell
python "$env:HERMES_HOME/scripts/24h_assistant.py" verify model
python "$env:HERMES_HOME/scripts/24h_assistant.py" verify vision
```

不得用用户截图替代自动生成的 Vision 验证图片。只有测试消息真正到达已保存的主投递目标后，才能将已配置的
消息连接器判定为投递可用。

## 生命周期诊断

明确区分出站产品模型密钥与入站 Hermes `API_SERVER_KEY`；绝不建议两者互相替代。排查更新或卸载问题前，
引导用户按仓库 README 执行仅产品数据导出和需要确认的数据清理流程。诊断过程中不得代替用户删除 Profile、
受管 Cron 任务、数据库或密钥。

说明正常 Profile 更新会保留本地用户数据。说明 Gateway/Cron 投递要求设备保持唤醒和联网，删除本地 Profile
不会撤销模型服务商处的模型密钥。
