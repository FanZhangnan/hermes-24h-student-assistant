import importlib.util
import io
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from lib.study_assistant.repository import Repository
from lib.study_assistant.seed_data import seed_demo


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO_TIMEZONE = ZoneInfo("UTC")


def load_script(test_case, filename, module_name):
    path = ROOT / "scripts" / filename
    test_case.assertTrue(path.is_file(), "Cron 提醒脚本必须存在：{}".format(filename))
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CronReminderScriptsTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.home = pathlib.Path(self.tempdir.name) / "hermes"
        self.repository = Repository(self.home / "24h-assistant" / "assistant.db")
        seed_demo(self.repository)

    def test_class_reminder_reads_ics_and_deduplicates(self):
        module = load_script(
            self,
            "24h_class_reminder.py",
            "class_reminder_test_module",
        )
        calendar_dir = pathlib.Path(self.tempdir.name) / "calendar"
        calendar_dir.mkdir()
        module.ICS_PATH = calendar_dir / "timetable.ics"
        module.URL_PATH = calendar_dir / "missing-url.txt"
        module.STATE_PATH = calendar_dir / "state.json"
        module.ICS_PATH.write_text(
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:demo1001-test\n"
            "DTSTART:20370804T100000\n"
            "DTEND:20370804T120000\n"
            "SUMMARY:DEMO1001 Machine Learning LEC\n"
            "LOCATION:Room 101\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n",
            encoding="utf-8",
        )
        self.repository.set_policy("class", 30, "22:30", "07:00")
        now = datetime(2037, 8, 4, 9, 35, tzinfo=DEMO_TIMEZONE)

        first = io.StringIO()
        second = io.StringIO()
        with patch.dict(os.environ, {"HERMES_HOME": str(self.home)}, clear=True):
            with redirect_stdout(first):
                self.assertEqual(module.main(now=now), 0)
            with redirect_stdout(second):
                self.assertEqual(module.main(now=now), 0)

        self.assertIn("课前提醒", first.getvalue())
        self.assertIn("DEMO1001", first.getvalue())
        self.assertIn("Room 101", first.getvalue())
        self.assertEqual(second.getvalue(), "")

    def test_assessment_reminder_uses_structured_database_and_deduplicates(self):
        module = load_script(
            self,
            "24h_assessment_reminder.py",
            "assessment_reminder_test_module",
        )
        state_path = pathlib.Path(self.tempdir.name) / "assessment-state.json"
        now = datetime(2037, 8, 4, 8, 15, tzinfo=DEMO_TIMEZONE)

        first = io.StringIO()
        second = io.StringIO()
        with patch.dict(os.environ, {"HERMES_HOME": str(self.home)}, clear=True):
            with redirect_stdout(first):
                self.assertEqual(module.main(now=now, state_path=state_path), 0)
            with redirect_stdout(second):
                self.assertEqual(module.main(now=now, state_path=state_path), 0)

        self.assertIn("今日学业计划", first.getvalue())
        self.assertIn("DEMO1001", first.getvalue())
        self.assertIn("25%", first.getvalue())
        self.assertIn("落后压缩、不顺延", first.getvalue())
        self.assertEqual(second.getvalue(), "")

        source = (ROOT / "scripts" / "24h_assessment_reminder.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("study_plan_sem2_2037.json", source)
        self.assertNotIn("24h_study_plan_build.py", source)

    def test_math_reminder_uses_seeded_math_block_and_deduplicates(self):
        module = load_script(
            self,
            "24h_math_plan_reminder.py",
            "math_reminder_test_module",
        )
        state_path = pathlib.Path(self.tempdir.name) / "demo1001-state.json"
        now = datetime(2037, 8, 1, 8, 20, tzinfo=DEMO_TIMEZONE)

        first = io.StringIO()
        second = io.StringIO()
        with patch.dict(os.environ, {"HERMES_HOME": str(self.home)}, clear=True):
            with redirect_stdout(first):
                self.assertEqual(module.main(now=now, state_path=state_path), 0)
            with redirect_stdout(second):
                self.assertEqual(module.main(now=now, state_path=state_path), 0)

        self.assertIn("DEMO1001 执行计划", first.getvalue())
        self.assertIn("数学 W1", first.getvalue())
        self.assertIn("10:00-11:30", first.getvalue())
        self.assertIn("完成标准", first.getvalue())
        self.assertEqual(second.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
