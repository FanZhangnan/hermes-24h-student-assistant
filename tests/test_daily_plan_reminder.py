import importlib.util
import io
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, time
from unittest.mock import patch

from lib.study_assistant.models import StudyBlock
from lib.study_assistant.repository import Repository
from lib.study_assistant.seed_data import seed_demo


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "24h_daily_plan_reminder.py"


def load_script(test_case):
    test_case.assertTrue(SCRIPT.is_file(), "每日计划提醒脚本必须存在")
    spec = importlib.util.spec_from_file_location("daily_plan_reminder", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DailyPlanReminderTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.home = pathlib.Path(self.tempdir.name) / "hermes"
        self.database = self.home / "24h-assistant" / "assistant.db"
        self.repository = Repository(self.database)
        seed_demo(self.repository)

    def test_render_today_includes_blocks_courses_and_milestones(self):
        module = load_script(self)
        assignment = self.repository.list_active_assignments()[0]
        self.repository.upsert_study_block(
            StudyBlock(
                "manual-a1-aug4",
                date(2037, 8, 4),
                time(13, 0),
                time(15, 0),
                "Assignment 1",
                "assignment",
                "planned",
                85,
                "manual",
                course_id=assignment.course_id,
                assignment_id=assignment.id,
                note="完成资料收集、数据探索和框架搭建",
                compressed=True,
            )
        )

        output = module.render_today(self.repository, date(2037, 8, 4))

        self.assertIn("今日学业计划", output)
        self.assertIn("DEMO1001", output)
        self.assertIn("13:00-15:00", output)
        self.assertIn("Assignment 1", output)
        self.assertIn("今日里程碑", output)
        self.assertIn("25%", output)
        self.assertIn("落后压缩、不顺延", output)

    def test_render_today_without_blocks_is_explicit(self):
        module = load_script(self)

        output = module.render_today(self.repository, date(2037, 12, 1))

        self.assertIn("今天没有已安排的学习时间块", output)

    def test_main_reports_missing_database_and_source_has_no_network_or_secrets(self):
        module = load_script(self)
        empty_home = pathlib.Path(self.tempdir.name) / "empty-hermes"
        stdout = io.StringIO()

        with patch.dict(os.environ, {"HERMES_HOME": str(empty_home)}, clear=True):
            with redirect_stdout(stdout):
                code = module.main()

        self.assertEqual(code, 1)
        self.assertIn("数据库尚未初始化", stdout.getvalue())
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "urllib",
            "requests",
            "subprocess",
            ".env",
            "auth.json",
            "API_KEY",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
