# 24h 留学助理

24h 留学助理是基于 Hermes One 的开源扩展包，面向需要管理课表、作业和学习计划的留学生。
“学业雷达”是当前开发阶段的名称。所有已上线功能不设置付费墙，阶段只表示开发顺序。

阶段 1 的结构化学业雷达最小闭环已实现：本地保存学生画像、课程、作业、里程碑、学习块、
数学基础计划和进度记录，并按“落后压缩、不顺延”生成每周计划。数据默认只保存在用户本地。

当前没有完整的 `.ics` 增量同步；截图 OCR 尚未实现；Course Profile 自动导入也尚未实现。
仓库不包含任何真实学校、课程、用户、消息目标、日志、数据库或密钥数据。

## 已实现功能

- 使用 SQLite schema v2 保存画像、课程、每周课程时段、作业、学习块、数学周、进度和截止提醒。
- 添加作业时按权重计算开工窗口，并生成 0/25/50/75/90/100 六级里程碑。
- 按 ISO 周生成计划，避开已确认课程和静默时段。
- 实际进度落后时压缩剩余工作，但不修改原截止日期。
- 提供中文 CLI、数据导出和需明确确认的数据清除命令。
- 提供课程、作业、每日计划、数学计划和冒烟测试的确定性提醒脚本。
- 提供 Hermes 版本、Gateway、Cron、模型路由、API Server 和数据库的脱敏诊断。
- 提供 `24h-student-assistant`、`24h-student-onboarding` 和
  `24h-student-assistant-doctor` 三个 Skills。
- macOS、Windows 和 Linux 均有命令入口；自动测试包含跨平台路径与安装器行为。

## 环境要求

- Hermes Agent `>=0.19.0`。
- Python `>=3.9`，运行时代码只使用 Python 标准库。
- Gateway 和 Cron 投递时，设备必须保持唤醒、联网并已连接消息平台。

密钥、Telegram Bot Token、`ALLOWED_USERS` 和 `HOME_CHANNEL` 必须保存在用户自己的 Hermes
Profile 中，不得写入仓库。产品数据库默认位于：

```text
~/.hermes/profiles/24h-assistant/24h-assistant/assistant.db
```

## 新建 Profile

取得本仓库的 Git 工作树后，在 macOS/Linux 运行：

```sh
python3 tools/install_local.py --profile 24h-assistant --clone-from default
```

Windows PowerShell：

```powershell
.\tools\install_local.ps1 --profile 24h-assistant --clone-from default
```

安装器会检查 Hermes 版本、创建独立 Profile、安装扩展包、设置本机回环 API Server 端口，
最后运行 Hermes doctor。安装器不会读取、打印或复制 `.env`、`auth.json` 或 API 密钥。

已有同名 Profile 时，先检查和导出数据。只有明确需要覆盖扩展包文件时才运行：

```sh
python3 tools/install_local.py --profile 24h-assistant --clone-from default --force
```

## 本地开发

macOS/Linux：

```sh
export HERMES_HOME="$HOME/.hermes/profiles/24h-assistant"
export ASSISTANT="$HERMES_HOME/scripts/24h_assistant.py"
python3 "$ASSISTANT" init
```

Windows PowerShell：

```powershell
$env:HERMES_HOME = Join-Path $env:USERPROFILE ".hermes/profiles/24h-assistant"
$Assistant = Join-Path $env:HERMES_HOME "scripts/24h_assistant.py"
python $Assistant init
```

### 初始化画像

以下值全部是虚构示例，请替换为用户确认的信息：

```sh
python3 "$ASSISTANT" profile set --school "Example University" --campus "Demo Campus" --city "Example City" --timezone UTC --language zh-CN
python3 "$ASSISTANT" profile show --json
python3 "$ASSISTANT" consent set vision_processing revoked --policy-version 2037-01-01
```

截图处理必须单独取得用户同意。当前截图 OCR 尚未实现，拒绝 Vision 时应改用结构化手动录入。

### 作业、计划和进度

```sh
python3 "$ASSISTANT" assignment add --course DEMO1001 --title "Assignment 1" --weight 15 --due "2037-08-21 15:00" --start-date "2037-07-29"
python3 "$ASSISTANT" plan generate --week 2037-W32
python3 "$ASSISTANT" plan show --json
python3 "$ASSISTANT" progress log --assignment-id <assignment-id> --percent 25 --note "框架已搭好"
```

高权重作业会获得更长的开工窗口。再次生成同一周时，系统只替换仍未完成的自动时间块，
保留手工、示例导入和已完成时间块。落后压缩、不顺延：补量必须放在原截止日前。

### 数学基础计划和示例数据

```sh
python3 "$ASSISTANT" math-plan init
python3 "$ASSISTANT" math-plan log --week 1 --percent 50 --minutes 90 --note "符号表完成一半"
python3 "$ASSISTANT" seed demo
```

`seed demo` 只导入虚构的 `DEMO1001` 等课程、2037 年日期和示例作业；可以重复执行，
不会创建重复记录。它不是任何真实学校的课程模板。

### 投递、策略与反馈

先用 Hermes 查看已经由用户配置的消息目标，再保存精确目标：

```sh
24h-assistant send --list
python3 "$ASSISTANT" delivery set --platform telegram --target "<用户确认的目标>"
python3 "$ASSISTANT" delivery test
python3 "$ASSISTANT" policy set course --lead-minutes 60 --quiet-start 22:30 --quiet-end 07:00
python3 "$ASSISTANT" feedback record reminder-1 complete
python3 "$ASSISTANT" cron smoke-create
```

`24h_daily_plan_reminder.py` 等提醒脚本只读取本地产品数据并输出中文消息，不读取凭证，也不调用模型。

## 诊断

离线诊断不显示原始配置或密钥：

```sh
python3 "$ASSISTANT" doctor
python3 "$ASSISTANT" doctor --json
```

下面两项会调用已配置模型，只有用户理解额度和数据边界并明确授权后才能运行：

```sh
python3 "$ASSISTANT" verify model
python3 "$ASSISTANT" verify vision
```

产品模型密钥与保护本地入站 API 的 `API_SERVER_KEY` 是两种不同凭证，不能互相替代。

## 自动测试

```sh
python3 -m unittest discover -s tests -v
python3 tools/release_guard.py --root . --mode public
```

发布守门会检查 Cron 契约、缺失脚本、运行时文件、个人目录、高风险密钥形态和隐私哈希标记。
CI 在 macOS、Windows 和 Linux 上运行测试，并在公开发布前执行同一守门命令。

## 更新

```sh
hermes profile update 24h-assistant
```

正常更新应保留 `.env`、记忆、会话、Profile 配置和用户数据。修改或删除提醒脚本前必须同步更新
`cron_contract.json`，并先运行发布守门，防止已存在的 Cron 任务失去脚本。

## 导出

导出仅属于本产品的数据：

```sh
python3 "$ASSISTANT" data export --output phase1-data.json
```

完整 Profile 归档可能包含私密配置和用户资料，必须按敏感文件处理：

```sh
hermes profile export 24h-assistant
```

## 卸载

卸载是破坏性操作。先导出，再通过精确确认短语删除受管 Cron 任务和本地产品数据：

```sh
python3 "$ASSISTANT" data clear --confirm CLEAR-24H-DATA
```

确认不再需要该 Profile 后，让 Hermes 显示交互式删除确认：

```sh
hermes profile delete 24h-assistant
```

删除本地文件不会撤销模型服务商签发的密钥。

## 本地运行限制

- 本地版不承诺真正的 24 小时投递 SLA；设备休眠、关机或断网时无法准时发送。
- 完整 `.ics` 增量同步尚未实现，当前仅支持已经结构化确认的数据。
- 截图 OCR 尚未实现；不得把临时聊天解析描述为已持久化能力。
- 不提供签证、移民、法律或报税建议。
- 经期、健身、选课和毕业规划属于后续阶段，当前未实现，也不会按付费状态隐藏。

## 隐私与安全

请阅读 [PRIVACY.md](PRIVACY.md) 和 [SECURITY.md](SECURITY.md)。公开 Issue、日志和截图中不得
包含密钥、用户 ID、消息目标、真实课表、作业内容或本机用户目录。

## 下一步

1. 完成跨 macOS/Windows 的 `.ics` 增量同步和逐项确认流程。
2. 实现跨平台截图 OCR，并要求用户逐项确认后才写入数据库。
3. 将 Course Profile 导入接入 Repository，不依赖聊天记录或临时 JSON。
4. 扩展 Hermes One 已支持的消息平台，并逐个平台保留端到端验收证据。
