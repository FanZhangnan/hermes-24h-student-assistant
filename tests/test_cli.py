import io
import json
import os
import pathlib
import stat
import tempfile
import unittest
from datetime import date, time
from unittest.mock import patch
from urllib.error import HTTPError

from lib.study_assistant import cli
from lib.study_assistant.models import CourseSession
from lib.study_assistant.repository import Repository


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def successful_loopback_opener(request, timeout):
    if request.full_url.endswith("/health"):
        return FakeResponse(200)
    raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, *args):
        self.calls.append(args)
        outputs = {
            ("--version",): (0, "Hermes Agent v0.19.0"),
            ("config", "check"): (0, "Configuration valid"),
            ("gateway", "status", "--deep"): (0, "Status: running"),
            ("cron", "status"): (0, "Scheduler: running"),
            ("status",): (
                0,
                "Model: test-model\nProvider: custom\nAPI Keys:\nsk-secret",
            ),
            ("send", "--list"): (0, "telegram"),
            ("config", "get", "platforms.api_server.extra.port"): (0, "8642"),
            (
                "send", "--to", "telegram",
                "24h 留学助理测试消息：消息平台连接成功。",
            ): (0, "Sent"),
            (
                "chat", "--quiet", "--source", "tool", "--query",
                "Reply with exactly MODEL_OK",
            ): (0, "MODEL_OK"),
            ("cron", "delete", "job-1"): (0, "Deleted"),
            (
                "cron", "create", "1m",
                "--name", "24h-assistant-smoke",
                "--deliver", "telegram",
                "--script", "24h_smoke_reminder.py",
                "--no-agent",
            ): (0, "Created job: abc123"),
        }
        if args[:4] == ("chat", "--quiet", "--source", "tool") and "--image" in args:
            return cli.CommandResult(0, "VISION_OK", "")
        return cli.CommandResult(outputs[args][0], outputs[args][1], "")


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.hermes_home = pathlib.Path(self.tempdir.name) / "hermes"
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.runner = FakeRunner()
        self.environment = patch.dict(
            os.environ,
            {"HERMES_HOME": str(self.hermes_home)},
            clear=True,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    @property
    def database(self):
        return self.hermes_home / "24h-assistant" / "assistant.db"

    def invoke(self, argv, opener=successful_loopback_opener):
        self.stdout.seek(0)
        self.stdout.truncate(0)
        self.stderr.seek(0)
        self.stderr.truncate(0)
        code = cli.main(
            argv,
            stdout=self.stdout,
            stderr=self.stderr,
            runner=self.runner,
            opener=opener,
        )
        return code, self.stdout.getvalue(), self.stderr.getvalue()

    def test_init_and_profile_round_trip(self):
        self.assertEqual(self.invoke(["init"])[0], 0)
        self.assertTrue(self.database.is_file())

        code, _, _ = self.invoke(
            [
                "profile", "set",
                "--school", "Example University",
                "--campus", "Demo Campus",
                "--city", "Example City",
                "--timezone", "UTC",
            ]
        )
        self.assertEqual(code, 0)

        code, output, _ = self.invoke(["profile", "show", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["school"], "Example University")
        self.assertNotIn("API_KEY", output)

    def test_invalid_timezone_and_quiet_time_return_usage_error(self):
        self.assertEqual(self.invoke(["init"])[0], 0)
        profile_code, _, _ = self.invoke(
            [
                "profile", "set",
                "--school", "Example University",
                "--campus", "Demo Campus",
                "--city", "Example City",
                "--timezone", "Example City",
            ]
        )
        policy_code, _, _ = self.invoke(
            [
                "policy", "set", "course",
                "--lead-minutes", "60",
                "--quiet-start", "25:00",
                "--quiet-end", "07:00",
            ]
        )
        self.assertEqual(profile_code, 2)
        self.assertEqual(policy_code, 2)

    def test_consent_delivery_policy_and_feedback_are_persisted(self):
        self.assertEqual(self.invoke(["init"])[0], 0)
        commands = [
            [
                "consent", "set", "vision_processing", "granted",
                "--policy-version", "2037-07-29",
            ],
            ["delivery", "set", "--platform", "telegram", "--target", "telegram"],
            [
                "policy", "set", "course",
                "--lead-minutes", "60",
                "--quiet-start", "22:30",
                "--quiet-end", "07:00",
            ],
            ["feedback", "record", "reminder-1", "complete"],
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.invoke(command)[0], 0)

        exported = Repository(self.database).export_data()
        self.assertEqual(exported["module_consent"][0]["granted"], 1)
        self.assertEqual(exported["delivery_target"][0]["platform"], "telegram")
        self.assertEqual(exported["reminder_policy"][0]["lead_minutes"], 60)
        self.assertEqual(exported["reminder_feedback"][0]["action"], "complete")

    def test_consent_rejects_unknown_state(self):
        code, _, _ = self.invoke(
            [
                "consent", "set", "vision_processing", "maybe",
                "--policy-version", "2037-07-29",
            ]
        )
        self.assertEqual(code, 2)

    def test_data_export_contains_only_product_tables(self):
        self.assertEqual(self.invoke(["init"])[0], 0)
        output = pathlib.Path(self.tempdir.name) / "phase0-data.json"

        code, _, _ = self.invoke(["data", "export", "--output", str(output)])

        self.assertEqual(code, 0)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(
            set(payload),
            {
                "student_profile",
                "module_consent",
                "reminder_policy",
                "delivery_target",
                "reminder_feedback",
                "managed_cron_job",
                "courses",
                "course_sessions",
                "assignments",
                "math_plan_weeks",
                "study_blocks",
                "progress_logs",
                "deadline_reminders",
            },
        )
        serialized = json.dumps(payload)
        for forbidden in (".env", "auth.json", "API_KEY"):
            self.assertNotIn(forbidden, serialized)
        self.assertFalse({"sessions", "conversations"} & set(payload))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_data_clear_requires_exact_confirmation_and_removes_managed_cron_first(self):
        self.assertEqual(self.invoke(["init"])[0], 0)
        repository = Repository(self.database)
        repository.register_cron_job("job-1", "smoke")
        wal = pathlib.Path(str(self.database) + "-wal")
        shm = pathlib.Path(str(self.database) + "-shm")
        wal.write_text("test", encoding="utf-8")
        shm.write_text("test", encoding="utf-8")

        self.assertEqual(
            self.invoke(["data", "clear", "--confirm", "clear"])[0],
            2,
        )
        self.assertTrue(self.database.exists())

        code, _, _ = self.invoke(
            ["data", "clear", "--confirm", "CLEAR-24H-DATA"]
        )

        self.assertEqual(code, 0)
        self.assertIn(("cron", "delete", "job-1"), self.runner.calls)
        self.assertFalse(self.database.exists())
        self.assertFalse(wal.exists())
        self.assertFalse(shm.exists())

    def test_doctor_json_is_redacted(self):
        self.assertEqual(self.invoke(["init"])[0], 0)
        self.assertEqual(
            self.invoke(
                ["delivery", "set", "--platform", "telegram", "--target", "telegram"]
            )[0],
            0,
        )

        code, output, _ = self.invoke(["doctor", "--json"])

        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output)["ok"])
        self.assertNotIn("sk-secret", output)

    def test_model_and_vision_verification_are_explicit_and_delete_fixture(self):
        self.assertEqual(self.invoke(["verify", "model"])[0], 0)
        self.assertEqual(self.invoke(["verify", "vision"])[0], 0)
        vision_call = next(call for call in self.runner.calls if "--image" in call)
        fixture = pathlib.Path(vision_call[vision_call.index("--image") + 1])
        self.assertFalse(fixture.exists())

    def test_delivery_test_uses_the_stored_primary_target(self):
        self.assertEqual(self.invoke(["init"])[0], 0)
        self.assertEqual(
            self.invoke(
                ["delivery", "set", "--platform", "telegram", "--target", "telegram"]
            )[0],
            0,
        )

        code, _, _ = self.invoke(["delivery", "test"])

        self.assertEqual(code, 0)
        self.assertIn(
            (
                "send", "--to", "telegram",
                "24h 留学助理测试消息：消息平台连接成功。",
            ),
            self.runner.calls,
        )

    def test_smoke_cron_is_no_agent_tracked_and_not_duplicated(self):
        self.assertEqual(self.invoke(["init"])[0], 0)
        self.assertEqual(
            self.invoke(
                ["delivery", "set", "--platform", "telegram", "--target", "telegram"]
            )[0],
            0,
        )

        first_code, _, _ = self.invoke(["cron", "smoke-create"])
        second_code, _, _ = self.invoke(["cron", "smoke-create"])

        self.assertEqual(first_code, 0)
        self.assertEqual(second_code, 1)
        create_call = (
            "cron", "create", "1m",
            "--name", "24h-assistant-smoke",
            "--deliver", "telegram",
            "--script", "24h_smoke_reminder.py",
            "--no-agent",
        )
        self.assertEqual(self.runner.calls.count(create_call), 1)
        jobs = Repository(self.database).list_managed_cron_jobs()
        self.assertEqual(jobs, [{"job_id": "abc123", "purpose": "smoke"}])

    def test_user_visible_help_success_errors_and_diagnostics_are_chinese(self):
        code, output, _ = self.invoke(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("24h 留学助理", output)
        self.assertIn("命令", output)
        self.assertIn("实际输入保持英文", output)
        self.assertIn("init", output)
        self.assertIn("profile", output)

        code, output, _ = self.invoke(["init"])
        self.assertEqual(code, 0)
        self.assertIn("已初始化", output)

        code, _, error = self.invoke(
            [
                "profile", "set",
                "--school", "Example University",
                "--campus", "Demo Campus",
                "--city", "Example City",
                "--timezone", "Example City",
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("时区", error)
        self.assertIn("用法：", error)
        self.assertNotIn("usage:", error)

        code, output, _ = self.invoke(["doctor"])
        self.assertEqual(code, 1)
        self.assertIn("通过", output)
        self.assertIn("失败", output)
        self.assertIn("修复建议", output)

        code, output, _ = self.invoke(["verify", "model"])
        self.assertEqual(code, 0)
        self.assertIn("模型验证通过", output)

    def set_demo_profile(self):
        code, _, _ = self.invoke(
            [
                "profile",
                "set",
                "--school",
                "Example University",
                "--campus",
                "Demo Campus",
                "--city",
                "Example City",
                "--timezone",
                "UTC",
                "--degree",
                "示例硕士项目",
                "--major",
                "示例专业",
            ]
        )
        self.assertEqual(code, 0)

    def test_assignment_add_persists_a1_and_six_milestones(self):
        self.set_demo_profile()

        code, output, error = self.invoke(
            [
                "assignment",
                "add",
                "--course",
                "DEMO1001",
                "--title",
                "Assignment 1",
                "--weight",
                "15",
                "--due",
                "2037-08-21 15:00",
                "--start-date",
                "2037-07-29",
            ]
        )

        self.assertEqual(code, 0, error)
        self.assertIn("已添加作业", output)
        repository = Repository(self.database)
        assignments = repository.list_active_assignments()
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0].title, "Assignment 1")
        self.assertEqual(assignments[0].due_at.isoformat(), "2037-08-21T15:00:00+00:00")
        reminders = repository.list_deadline_reminders(assignments[0].id)
        self.assertEqual([item.target_percent for item in reminders], [0, 25, 50, 75, 90, 100])

    def test_assignment_add_rejects_invalid_weight_and_due_time_in_chinese(self):
        self.set_demo_profile()
        base = [
            "assignment",
            "add",
            "--course",
            "DEMO1001",
            "--title",
            "Assignment 1",
        ]

        weight_code, _, weight_error = self.invoke(
            base + ["--weight", "101", "--due", "2037-08-21 15:00"]
        )
        due_code, _, due_error = self.invoke(
            base + ["--weight", "15", "--due", "2037/08/21 15:00"]
        )

        self.assertEqual(weight_code, 2)
        self.assertEqual(due_code, 2)
        self.assertIn("权重", weight_error)
        self.assertIn("截止时间", due_error)

    def test_plan_generate_show_and_progress_log_form_a_persisted_loop(self):
        self.set_demo_profile()
        add_code, _, _ = self.invoke(
            [
                "assignment",
                "add",
                "--course",
                "DEMO1001",
                "--title",
                "Assignment 1",
                "--weight",
                "15",
                "--due",
                "2037-08-21 15:00",
                "--start-date",
                "2037-07-29",
            ]
        )
        self.assertEqual(add_code, 0)
        repository = Repository(self.database)
        assignment = repository.list_active_assignments()[0]
        repository.upsert_course_session(
            CourseSession(
                "session-demo1001-monday",
                assignment.course_id,
                0,
                time(15, 30),
                time(17, 30),
                valid_from=date(2037, 7, 27),
                valid_to=date(2037, 10, 30),
            )
        )

        generate_code, generate_output, generate_error = self.invoke(
            ["plan", "generate", "--week", "2037-W32"]
        )
        show_code, show_output, show_error = self.invoke(["plan", "show", "--json"])
        progress_code, progress_output, progress_error = self.invoke(
            [
                "progress",
                "log",
                "--assignment-id",
                assignment.id,
                "--percent",
                "25",
                "--note",
                "框架已搭好",
            ]
        )

        self.assertEqual(generate_code, 0, generate_error)
        self.assertIn("已生成 2037-W32", generate_output)
        self.assertEqual(show_code, 0, show_error)
        payload = json.loads(show_output)
        self.assertTrue(payload["blocks"])
        self.assertIn("compressed", payload)
        self.assertTrue(
            all("2037-08-03" <= item["block_date"] <= "2037-08-09" for item in payload["blocks"])
        )
        self.assertEqual(progress_code, 0, progress_error)
        self.assertIn("已记录作业进度", progress_output)
        latest = repository.latest_progress(assignment_id=assignment.id)
        self.assertEqual(latest.percent, 25)
        self.assertEqual(latest.note, "框架已搭好")

    def test_math_plan_init_log_and_full_demo1001_seed_are_idempotent(self):
        self.assertEqual(self.invoke(["init"])[0], 0)

        first_code, first_output, first_error = self.invoke(["math-plan", "init"])
        second_code, _, second_error = self.invoke(["math-plan", "init"])
        log_code, log_output, log_error = self.invoke(
            [
                "math-plan",
                "log",
                "--week",
                "1",
                "--percent",
                "50",
                "--minutes",
                "90",
                "--note",
                "符号表完成一半",
            ]
        )
        seed_code, seed_output, seed_error = self.invoke(["seed", "demo"])
        repeat_code, _, repeat_error = self.invoke(["seed", "demo"])

        self.assertEqual(first_code, 0, first_error)
        self.assertIn("已初始化 DEMO1001 七周数学计划", first_output)
        self.assertEqual(second_code, 0, second_error)
        self.assertEqual(log_code, 0, log_error)
        self.assertIn("已记录数学计划第 1 周进度", log_output)
        self.assertEqual(seed_code, 0, seed_error)
        self.assertIn("已导入 DEMO1001", seed_output)
        self.assertEqual(repeat_code, 0, repeat_error)

        repository = Repository(self.database)
        weeks = repository.list_math_plan_weeks("demo-math-plan")
        self.assertEqual(len(weeks), 7)
        latest = repository.latest_progress(math_plan_week_id=weeks[0].id)
        self.assertEqual(latest.percent, 50)
        self.assertEqual(latest.minutes, 90)
        self.assertEqual(weeks[0].hard_deadline, date(2037, 9, 16))
        self.assertEqual(len(repository.list_courses()), 4)


if __name__ == "__main__":
    unittest.main()
