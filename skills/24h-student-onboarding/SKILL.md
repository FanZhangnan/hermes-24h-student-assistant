---
name: 24h-student-onboarding
description: 在 macOS 或 Windows 上收集并确认学校、位置、语言、消息目标、提醒策略和独立同意项，建立 24h 留学助理阶段 0 画像。
version: 0.1.0
platforms: [linux, macos, windows]
---

# 24h 留学助理首次设置

当前只收集阶段 0 所需字段：

- 学校、校区、城市、IANA 格式时区和提醒语言；
- 一个 Hermes 消息平台及其精确的主投递目标；
- 提前提醒时间，以及 24 小时制 `HH:MM` 格式的免打扰开始/结束时间；
- `vision_processing` 的独立选择：`granted` 或 `revoked`。

询问 Vision 同意项前，必须说明截图将经由用户配置的 API 端点发送到上游模型。如果用户拒绝，
改为提供结构化手动录入。不得因用户使用了其他功能而推定其同意 Vision。

## 写入前确认

展示包含全部已收集字段和每项同意选择的确认摘要。只有用户明确确认该摘要后，才能执行写入命令。

初始化本地数据库后，每次只写入一类数据。macOS/Linux 使用 `python3`，Windows PowerShell 使用 `python`。

```bash
python3 "$HERMES_HOME/scripts/24h_assistant.py" init
python3 "$HERMES_HOME/scripts/24h_assistant.py" profile set --school "<school>" --campus "<campus>" --city "<city>" --timezone "<timezone>" --language "<language>"
python3 "$HERMES_HOME/scripts/24h_assistant.py" consent set vision_processing <granted-or-revoked> --policy-version 2026-07-29
python3 "$HERMES_HOME/scripts/24h_assistant.py" delivery set --platform "<platform>" --target "<target>"
python3 "$HERMES_HOME/scripts/24h_assistant.py" policy set course --lead-minutes <minutes> --quiet-start <HH:MM> --quiet-end <HH:MM>
```

```powershell
python "$env:HERMES_HOME/scripts/24h_assistant.py" init
python "$env:HERMES_HOME/scripts/24h_assistant.py" profile set --school "<school>" --campus "<campus>" --city "<city>" --timezone "<timezone>" --language "<language>"
python "$env:HERMES_HOME/scripts/24h_assistant.py" consent set vision_processing <granted-or-revoked> --policy-version 2026-07-29
python "$env:HERMES_HOME/scripts/24h_assistant.py" delivery set --platform "<platform>" --target "<target>"
python "$env:HERMES_HOME/scripts/24h_assistant.py" policy set course --lead-minutes <minutes> --quiet-start <HH:MM> --quiet-end <HH:MM>
```

报告校验错误时不得修改用户输入。最后显示 `profile show --json` 的结果，然后转到诊断 Skill 执行就绪检查。
