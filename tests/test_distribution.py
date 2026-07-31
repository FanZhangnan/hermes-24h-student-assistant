import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def parse_simple_distribution_manifest(contents):
    metadata = {}
    distribution_owned = []
    reading_distribution_owned = False

    for line in contents.splitlines():
        if line == "distribution_owned:":
            if reading_distribution_owned:
                raise ValueError("distribution_owned may only appear once")
            reading_distribution_owned = True
            continue
        if reading_distribution_owned and line.startswith("  - "):
            distribution_owned.append(line.removeprefix("  - "))
            continue
        if reading_distribution_owned and line.startswith(" "):
            raise ValueError("distribution_owned only accepts list entries")
        if line and not line.startswith(" "):
            key, value = line.split(": ", maxsplit=1)
            if key in metadata:
                raise ValueError(f"duplicate manifest field: {key}")
            metadata[key] = value.strip('"')
            reading_distribution_owned = False

    return metadata, distribution_owned


def tracked_repository_file_names():
    return {
        path.name
        for path in ROOT.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(ROOT).parts
    }


class DistributionContractTests(unittest.TestCase):
    def test_distribution_manifest_declares_profile_contract(self):
        manifest = ROOT / "distribution.yaml"
        self.assertTrue(manifest.is_file(), "distribution.yaml must be included")

        contents = manifest.read_text(encoding="utf-8")
        metadata, distribution_owned = parse_simple_distribution_manifest(contents)
        self.assertEqual(
            metadata,
            {
                "name": "24h-assistant",
                "version": "0.2.0",
                "description": "基于 Hermes One 的 24h 留学助理阶段 0/1 扩展包",
                "hermes_requires": ">=0.19.0",
                "author": "24h 留学助理",
                "license": "MIT",
            },
        )
        self.assertEqual(distribution_owned, ["SOUL.md", "skills", "scripts", "lib"])
        self.assertNotIn("OPENAI_API_KEY=", contents)

    def test_distribution_excludes_local_credentials_and_state(self):
        forbidden_names = {".env", "auth.json", "assistant.db", "state.db"}
        found_names = tracked_repository_file_names()
        self.assertFalse(forbidden_names & found_names)

    def test_public_repository_includes_safety_and_automation_contracts(self):
        for relative in (
            "LICENSE",
            "PRIVACY.md",
            "SECURITY.md",
            ".env.example",
            "config.example.yaml",
            "cron_contract.json",
            "privacy_denylist.sha256",
            "tools/release_guard.py",
            ".github/workflows/ci.yml",
        ):
            self.assertTrue(
                (ROOT / relative).is_file(),
                "公开仓库缺少 {}".format(relative),
            )

        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("python3 -m unittest discover -s tests -v", workflow)
        self.assertIn("tools/release_guard.py --root . --mode public", workflow)

        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", license_text)

    def test_distribution_contains_every_deterministic_cron_script(self):
        required_scripts = {
            "24h_class_reminder.py",
            "24h_assessment_reminder.py",
            "24h_math_plan_reminder.py",
            "24h_daily_plan_reminder.py",
            "24h_smoke_reminder.py",
        }
        scripts = {
            path.name for path in (ROOT / "scripts").glob("*.py") if path.is_file()
        }
        self.assertTrue(
            required_scripts <= scripts,
            "发行包缺少 Cron 脚本：{}".format(
                ", ".join(sorted(required_scripts - scripts))
            ),
        )

    def test_phase_zero_skills_have_cross_platform_metadata(self):
        skill_versions = {
            "24h-student-assistant": "0.2.0",
            "24h-student-onboarding": "0.1.0",
            "24h-student-assistant-doctor": "0.1.0",
        }
        for skill_name, version in skill_versions.items():
            with self.subTest(skill=skill_name):
                path = ROOT / "skills" / skill_name / "SKILL.md"
                self.assertTrue(path.is_file(), "{} must be included".format(path))
                contents = path.read_text(encoding="utf-8")
                self.assertTrue(contents.startswith("---\n"))
                frontmatter = contents.split("---\n", 2)[1]
                self.assertIn("name: {}\n".format(skill_name), frontmatter)
                self.assertRegex(frontmatter, r"(?m)^description: .+$")
                self.assertIn("version: {}\n".format(version), frontmatter)
                self.assertIn("platforms: [linux, macos, windows]\n", frontmatter)
                self.assertIn(
                    'python3 "$HERMES_HOME/scripts/24h_assistant.py"',
                    contents,
                )
                self.assertIn(
                    'python "$env:HERMES_HOME/scripts/24h_assistant.py"',
                    contents,
                )

    def test_onboarding_skill_uses_only_confirmed_cli_writes(self):
        contents = (
            ROOT / "skills" / "24h-student-onboarding" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'python3 "$HERMES_HOME/scripts/24h_assistant.py" profile set',
            contents,
        )
        self.assertIn(
            'python "$env:HERMES_HOME/scripts/24h_assistant.py" profile set',
            contents,
        )
        for command in ("consent set", "delivery set", "policy set"):
            self.assertIn(command, contents)
        self.assertIn("确认摘要", contents)

    def test_doctor_skill_never_displays_credentials(self):
        contents = (
            ROOT / "skills" / "24h-student-assistant-doctor" / "SKILL.md"
        ).read_text(encoding="utf-8")
        for protected in (".env", "API 密钥", "平台令牌"):
            self.assertIn(protected, contents)
        self.assertIn("绝不显示", contents)
        self.assertIn("先运行离线检查", contents)
        self.assertIn("明确授权", contents)
        self.assertIn("绝不运行 `hermes doctor --fix`", contents)

    def test_readme_documents_safe_profile_lifecycle(self):
        contents = (ROOT / "README.md").read_text(encoding="utf-8")
        for command in (
            "hermes profile update 24h-assistant",
            "hermes profile export 24h-assistant",
            "hermes profile delete 24h-assistant",
            "data export --output phase1-data.json",
            "data clear --confirm CLEAR-24H-DATA",
        ):
            self.assertIn(command, contents)
        deletion_section = contents.split("## 卸载", 1)[1]
        self.assertNotIn("--yes", deletion_section)
        self.assertIn("受管 Cron 任务", deletion_section)
        self.assertIn("本地产品数据", deletion_section)
        self.assertIn("破坏性", deletion_section)
        normalized = " ".join(contents.split())
        for preserved in (".env", "记忆", "会话", "用户数据"):
            self.assertIn(preserved, normalized)
        self.assertIn("API_SERVER_KEY", contents)
        self.assertIn("保持唤醒", contents)

    def test_core_product_documents_are_chinese_first(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for heading in (
            "## 新建 Profile",
            "## 本地开发",
            "## 诊断",
            "## 更新",
            "## 导出",
            "## 卸载",
            "## 本地运行限制",
        ):
            self.assertIn(heading, readme)

        soul = (ROOT / "SOUL.md").read_text(encoding="utf-8")
        self.assertIn("面向留学生", soul)
        self.assertIn("不设置付费墙", soul)
        self.assertIn("明确同意", soul)

        for skill_path in (ROOT / "skills").glob("*/SKILL.md"):
            with self.subTest(skill=skill_path.parent.name):
                contents = skill_path.read_text(encoding="utf-8")
                self.assertIn("description: ", contents)
                self.assertRegex(contents, r"description: .*[\u4e00-\u9fff]")
                self.assertRegex(contents, r"(?m)^# .*[一-鿿].*$")


    def test_readme_matches_current_phase_one_code_and_acceptance_state(self):
        contents = (ROOT / "README.md").read_text(encoding="utf-8")

        for fact in (
            "阶段 1 的结构化学业雷达最小闭环已实现",
            "完整 `.ics` 增量同步尚未实现",
            "截图 OCR 尚未实现",
            "落后压缩、不顺延",
            "macOS、Windows 和 Linux",
            "所有已上线功能不设置付费墙",
            "数据默认只保存在用户本地",
            "`ALLOWED_USERS`",
            "`HOME_CHANNEL`",
            "~/.hermes/profiles/24h-assistant/24h-assistant/assistant.db",
            "python $Assistant init",
            "24h-student-assistant",
            "24h-student-onboarding",
            "24h-student-assistant-doctor",
            "24h_daily_plan_reminder.py",
            "release_guard.py --root . --mode public",
        ):
            self.assertIn(fact, contents)

        self.assertNotIn("学业雷达业务功能尚未实现", contents)
        self.assertIn(
            'export HERMES_HOME="$HOME/.hermes/profiles/24h-assistant"',
            contents,
        )

        for command in (
            "profile set --school",
            "profile show --json",
            "consent set vision_processing",
            "delivery set --platform telegram --target",
            "delivery test",
            "policy set course --lead-minutes",
            "feedback record",
            "doctor --json",
            "verify model",
            "verify vision",
            "cron smoke-create",
            "assignment add --course DEMO1001",
            "plan generate --week 2037-W32",
            "plan show --json",
            "progress log --assignment-id",
            "math-plan init",
            "math-plan log --week",
            "seed demo",
            "python3 -m unittest discover -s tests -v",
        ):
            self.assertIn(command, contents)

        for unsupported_claim in (
            "macOS 已完成真实验收",
            "Telegram 主链路端到端验收已通过",
        ):
            self.assertNotIn(unsupported_claim, contents)

        skill = (ROOT / "skills/24h-student-assistant/SKILL.md").read_text(
            encoding="utf-8"
        )
        for fact in (
            "阶段 1",
            "assignment add",
            "plan generate",
            "progress log",
            "math-plan",
            "落后压缩、不顺延",
        ):
            self.assertIn(fact, skill)


if __name__ == "__main__":
    unittest.main()
