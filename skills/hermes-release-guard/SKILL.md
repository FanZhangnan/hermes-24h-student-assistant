---
name: hermes-release-guard
description: 在安装或更新 Hermes Profile、修改 distribution.yaml 或 Cron 脚本、合并主分支、push、创建公开仓库或发布扩展包前使用。强制运行仓库自带的确定性守门，检查安装后脚本契约、真实 Profile Cron 引用、运行时文件、个人路径、隐私标记和高风险密钥形态，并禁止回显敏感值。
---

# Hermes 发布守门

本 Skill 负责选择检查模式、调用仓库自己的 `tools/release_guard.py` 并解释结果。真正的发布约束必须存在于
版本化脚本和 CI 中，不能只依赖 Agent 记忆、肉眼审查或本 Skill 的文字。

## 何时必须运行

- 安装或更新 Hermes Profile 前。
- 新增、修改、移动或删除 Cron 提醒脚本后。
- 修改 `distribution.yaml`、`cron_contract.json` 或安装器后。
- 合并到主分支、push 或创建 GitHub 发布前。
- 从私有运营仓库导出公开仓库前。

## 执行流程

1. 确认仓库根目录和发布目标。个人运营仓库使用 `private`；任何可被公众访问的仓库使用 `public`。
2. 先运行项目测试。不得把“单元测试通过”当成发布守门通过。
3. 从本 Skill 调用仓库内的唯一守门实现：

```sh
python3 <skill-dir>/scripts/release_guard.py --root <repository-root> --mode private --profile <hermes-profile-root> --json
```

公开仓库：

```sh
python3 <skill-dir>/scripts/release_guard.py --root <repository-root> --mode public --json
```

4. 退出码非零或 JSON 中 `ok` 不是 `true` 时，停止安装、合并、push 和发布。逐项修复后重新运行完整检查。
5. 守门通过后，再检查 `git status`、目标远端和可见性；公开仓库必须使用全新、经过审计的历史。
6. 保存测试数量、守门 JSON、提交 ID、远端可见性和 push 结果作为验收证据。不得保存凭证值。

## 强制规则

- 不直接用 `rg`、`grep` 或终端打印匹配行来扫描密钥；这可能把密钥回显到日志。
- 不假设 `gitleaks`、`trufflehog`、Node、npm 或其他外部工具已安装。它们只能作为额外检查，不能替代仓库守门。
- 不检查系统 `crontab` 来推断 Hermes 任务。只读取用户明确指定的 Hermes Profile Cron 状态。
- 不读取或输出 `.env`、`auth.json`、Bot Token、API 密钥、用户 ID、消息目标或私密日历 URL。
- 执行时可以解析绝对路径，但用户报告和验收记录必须写成 `<skill-dir>`、`<repository-root>` 和 `<profile-root>`，不得暴露本机用户名目录。
- 删除脚本前必须更新 `cron_contract.json`，并为现有 Profile 任务提供暂停、迁移或删除方案。
- `public` 模式必须拒绝数据库、日志、运行时状态、个人目录和隐私哈希清单命中的标识。
- 任何失败都不得用“时间紧”“测试已过”“只是演示”“之后再清理”绕过。

## 失败处理

| 守门规则 | 处理方式 |
|---|---|
| `cron_contract` | 恢复脚本或同步更新契约和任务迁移。 |
| `orphan_cron_script` | 先暂停受影响任务，修复脚本或迁移任务，再测试。 |
| `runtime_state` / `public_log` | 从公开导出中排除；不要只写进 README 声明。 |
| `personal_path` / `private_identifier` | 改为相对路径、占位符或虚构示例，并重新扫描全部文件。 |
| `secret_pattern` | 立即停止发布；若值曾公开，先撤销和轮换，再清理历史。 |

## 常见错误判断

| 借口 | 实际要求 |
|---|---|
| “全部单元测试通过” | 单元测试不等于安装后的 Cron 契约和隐私检查。 |
| “先 push，稍后删除” | 公开 Git 历史和缓存可能已经复制内容。先修复再 push。 |
| “肉眼看过，没有密钥” | 必须运行确定性守门并保留脱敏 JSON。 |
| “外部扫描器更专业” | 可额外使用，但不得替代仓库自己的稳定契约。 |
| “系统定时任务看起来正常” | Hermes Profile Cron 才是本项目的检查对象。 |

## 输出要求

向用户报告：检查模式、测试结果、守门是否通过、失败规则与相对路径、提交和远端状态。只报告最少必要信息，
绝不粘贴命中文本或敏感值。
