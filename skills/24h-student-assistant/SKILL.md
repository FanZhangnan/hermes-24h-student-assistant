---
name: 24h-student-assistant
description: 路由 24h 留学助理阶段 0 基础与阶段 1 结构化学业雷达的首次设置、作业、周计划、进度、数学基础计划、消息投递和 Hermes 诊断请求。
version: 0.2.0
platforms: [linux, macos, windows]
---

# 24h 留学助理

学业雷达是 24h 留学助理的第一个上线阶段。所有已上线功能对全部用户开放；绝不添加会员、套餐或模块权限检查。

阶段 1 已提供结构化作业、周计划、进度日志、数学基础计划和每日学业提醒脚本。

## 请求路由

- 首次建立用户画像、独立同意项、主消息投递目标和提醒策略时，使用 `24h-student-onboarding`。
- 安装、模型、Vision、Gateway、Cron、API Server、数据库或消息平台出现问题时，使用 `24h-student-assistant-doctor`。
- 结构化数据的读写必须通过 `$HERMES_HOME/scripts/24h_assistant.py` 完成。
- 用户确认课程、作业标题、权重、截止时间和开工日后，使用 `assignment add` 写入数据库。
- 用户要求生成一周计划时，使用 `plan generate --week YYYY-Www`；展示前可用 `plan show --json` 读取持久化结果。
- 用户报告作业完成度时，使用 `progress log` 追加日志，不覆盖历史记录。
- 七周数学基础计划使用 `math-plan init` 和 `math-plan log`；`seed demo` 只导入虚构示例数据，不代表用户的真实课表。
- 规划规则固定为“落后压缩、不顺延”：绝不修改原作业截止日或数学计划硬截止。

macOS/Linux 示例：

```bash
python3 "$HERMES_HOME/scripts/24h_assistant.py" assignment add --course DEMO1001 --title "Assignment 1" --weight 15 --due "2037-08-21 15:00" --start-date "2037-07-29"
python3 "$HERMES_HOME/scripts/24h_assistant.py" plan generate --week 2037-W32
python3 "$HERMES_HOME/scripts/24h_assistant.py" progress log --assignment-id <assignment-id> --percent 25 --note "框架已搭好"
```

Windows PowerShell 示例：

```powershell
python "$env:HERMES_HOME/scripts/24h_assistant.py" plan show --json
python "$env:HERMES_HOME/scripts/24h_assistant.py" math-plan log --week 1 --percent 50 --minutes 90
```

根据操作系统选择 Python 解释器。例如，macOS/Linux 诊断命令为：

```bash
python3 "$HERMES_HOME/scripts/24h_assistant.py" doctor --json
```

Windows PowerShell：

```powershell
python "$env:HERMES_HOME/scripts/24h_assistant.py" doctor --json
```

## 安全边界

- 写入用户提供的结构化数据前，必须先显示确认摘要。
- 绝不推断用户的性别、健康状态、学习能力或同意意愿。
- 绝不编造用户画像、课表、消息平台或诊断事实。
- 产品记录必须保存在扩展包数据库中，不得写入 Hermes Memory 或 `state.db`。
- 完整 `.ics` 同步和 Course Profile 自动导入尚未进入正式扩展包；不得把临时聊天 JSON 描述为已持久化能力。
- macOS 和 Windows 笔记本必须保持唤醒、联网并已连接消息平台，才能实时投递。设备休眠或关机时不得承诺按时投递。
- 经期、健身、选课和毕业规划属于后续阶段；不得基于付费状态解锁或隐藏它们。
- 不处理签证、移民、法律或报税建议。
