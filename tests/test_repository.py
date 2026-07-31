import importlib
import os
import pathlib
import sqlite3
import stat
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import date, datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from lib.study_assistant import models
from lib.study_assistant.models import (
    Assignment,
    Course,
    CourseSession,
    DeadlineReminder,
    DeliveryTarget,
    MathPlanWeek,
    ProgressLog,
    StudentProfile,
    StudyBlock,
)
from lib.study_assistant.paths import RuntimePaths
from lib.study_assistant.repository import Repository


class RepositoryTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.home = pathlib.Path(self.tempdir.name)

    def test_paths_are_scoped_to_hermes_home(self):
        with patch.dict(os.environ, {"HERMES_HOME": str(self.home)}):
            paths = RuntimePaths.from_environment()

        self.assertEqual(paths.database, self.home / "24h-assistant" / "assistant.db")

    def test_non_windows_default_uses_dot_hermes_in_user_home(self):
        with patch.dict(os.environ, {"HOME": str(self.home)}, clear=True):
            with patch("lib.study_assistant.paths.os.name", "posix"):
                paths = RuntimePaths.from_environment()

        self.assertEqual(paths.hermes_home, self.home / ".hermes")

    def test_runtime_models_are_immutable(self):
        paths = RuntimePaths(self.home, self.home / "data", self.home / "data/db")
        profile = StudentProfile("Example University", "Demo Campus", "Example City", "UTC")
        delivery = DeliveryTarget("telegram", "telegram")

        for instance, attribute in (
            (paths, "database"),
            (profile, "school"),
            (delivery, "platform"),
        ):
            with self.subTest(model=type(instance).__name__):
                with self.assertRaises(FrozenInstanceError):
                    setattr(instance, attribute, None)

    def test_windows_default_uses_local_app_data(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.home)}, clear=True):
            with patch("lib.study_assistant.paths.os.name", "nt"):
                paths = RuntimePaths.from_environment()

        self.assertEqual(paths.hermes_home, self.home / "hermes")

    def test_windows_default_requires_local_app_data(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("lib.study_assistant.paths.os.name", "nt"):
                with self.assertRaisesRegex(RuntimeError, "LOCALAPPDATA"):
                    RuntimePaths.from_environment()

    def test_windows_initialization_skips_posix_permissions(self):
        repo = Repository(self.home / "assistant.db")

        with patch("lib.study_assistant.repository.os.name", "nt"):
            with patch("pathlib.Path.chmod") as chmod:
                repo.initialize()

        chmod.assert_not_called()

    def test_initialize_creates_phase_zero_tables(self):
        repo = Repository(self.home / "assistant.db")
        repo.initialize()

        with sqlite3.connect(repo.database) as connection:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            migration = connection.execute(
                "SELECT version FROM schema_migrations"
            ).fetchone()
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

        self.assertTrue(
            {
                "schema_migrations",
                "student_profile",
                "module_consent",
                "reminder_policy",
                "delivery_target",
                "reminder_feedback",
                "managed_cron_job",
            }.issubset(names)
        )
        self.assertEqual(migration, (1,))
        self.assertEqual(journal_mode, "wal")

        with repo._connect() as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)

        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(repo.database.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(repo.database.stat().st_mode), 0o600)

    def test_initialize_creates_phase_one_tables_indexes_and_models(self):
        repo = Repository(self.home / "assistant.db")
        repo.initialize()

        with sqlite3.connect(repo.database) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            indexes = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
            migrations = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()

        self.assertTrue(
            {
                "courses",
                "course_sessions",
                "assignments",
                "study_blocks",
                "math_plan_weeks",
                "progress_logs",
                "deadline_reminders",
            }.issubset(tables)
        )
        self.assertTrue(
            {
                "assignments_status_due",
                "course_sessions_weekday_range",
                "study_blocks_date_status",
                "progress_assignment_time",
                "progress_math_week_time",
                "math_plan_date_status",
                "reminders_status_time",
            }.issubset(indexes)
        )
        self.assertEqual(migrations, [(1,), (2,)])

        for model_name in (
            "Course",
            "CourseSession",
            "Assignment",
            "StudyBlock",
            "MathPlanWeek",
            "ProgressLog",
            "DeadlineReminder",
        ):
            with self.subTest(model=model_name):
                self.assertTrue(hasattr(models, model_name))

    def test_profile_round_trip(self):
        profile = StudentProfile("Example University", "Demo Campus", "Example City", "UTC")
        repo = Repository(self.home / "assistant.db")
        repo.initialize()

        repo.save_profile(profile)

        self.assertEqual(repo.get_profile(), profile)

    def test_only_one_primary_delivery_target_exists(self):
        repo = Repository(self.home / "assistant.db")
        repo.initialize()

        repo.set_primary_delivery(DeliveryTarget("telegram", "telegram"))
        repo.set_primary_delivery(DeliveryTarget("discord", "discord:#study"))

        self.assertEqual(repo.get_primary_delivery().platform, "discord")
        with sqlite3.connect(repo.database) as connection:
            primary_count = connection.execute(
                "SELECT COUNT(*) FROM delivery_target WHERE is_primary = 1"
            ).fetchone()[0]
        self.assertEqual(primary_count, 1)

    def test_consent_revocation_preserves_grant_and_revoke_timestamps(self):
        repo = Repository(self.home / "assistant.db")
        repo.initialize()

        repo.set_consent("vision_processing", True, "2037-07-29")
        repo.set_consent("vision_processing", False, "2037-07-29")

        self.assertFalse(repo.list_consents()["vision_processing"])
        with sqlite3.connect(repo.database) as connection:
            row = connection.execute(
                "SELECT granted_at, revoked_at FROM module_consent "
                "WHERE module = 'vision_processing'"
            ).fetchone()
        self.assertTrue(row[0])
        self.assertTrue(row[1])

    def test_policy_is_persisted(self):
        repo = Repository(self.home / "assistant.db")
        repo.initialize()

        repo.set_policy("course", 60, "22:30", "07:00")

        with sqlite3.connect(repo.database) as connection:
            row = connection.execute(
                "SELECT lead_minutes, quiet_start, quiet_end "
                "FROM reminder_policy WHERE event_type = 'course'"
            ).fetchone()
        self.assertEqual(row, (60, "22:30", "07:00"))

    def test_feedback_accepts_known_actions_and_rejects_unknown_action(self):
        repo = Repository(self.home / "assistant.db")
        repo.initialize()

        repo.record_feedback("reminder-1", "complete")
        with self.assertRaisesRegex(ValueError, "complete、later 或 useless"):
            repo.record_feedback("reminder-1", "clicked")

        with sqlite3.connect(repo.database) as connection:
            actions = connection.execute(
                "SELECT action FROM reminder_feedback ORDER BY id"
            ).fetchall()
        self.assertEqual(actions, [("complete",)])

    def test_phase_one_course_assignment_session_and_reminder_round_trip(self):
        repo = Repository(self.home / "assistant.db")
        repo.initialize()
        for method_name in (
            "upsert_course",
            "upsert_course_session",
            "upsert_assignment",
            "upsert_deadline_reminder",
            "get_course_by_code",
            "list_course_sessions",
            "get_assignment",
            "list_deadline_reminders",
        ):
            self.assertTrue(hasattr(repo, method_name), method_name)
        timezone = ZoneInfo("UTC")
        course = Course(
            "course-demo1001",
            "DEMO1001",
            "Machine Learning for Data Scientists",
            "DEMO-TERM",
            "UTC",
            "https://example.invalid/courses/DEMO1001",
        )
        session = CourseSession(
            "session-demo1001-lec",
            course.id,
            1,
            time(10, 0),
            time(12, 0),
            "Demo Campus",
            date(2037, 7, 27),
            date(2037, 10, 30),
            "demo-university-demo1001-lec",
        )
        assignment = Assignment(
            "assignment-demo1001-a1",
            course.id,
            "Assignment 1",
            "assignment",
            15,
            datetime(2037, 8, 21, 15, 0, tzinfo=timezone),
            date(2037, 7, 29),
        )
        reminder = DeadlineReminder(
            "reminder-demo1001-a1-25",
            assignment.id,
            datetime(2037, 8, 4, 9, 0, tzinfo=timezone),
            "milestone",
            "完成资料收集/数据探索/框架搭建",
            target_percent=25,
        )

        repo.upsert_course(course)
        repo.upsert_course_session(session)
        repo.upsert_assignment(assignment)
        repo.upsert_deadline_reminder(reminder)

        self.assertEqual(repo.get_course_by_code("DEMO1001"), course)
        self.assertEqual(repo.list_course_sessions(), [session])
        self.assertEqual(repo.get_assignment(assignment.id), assignment)
        self.assertEqual(repo.list_deadline_reminders(assignment.id), [reminder])

    def test_math_plan_and_progress_round_trip(self):
        repo = Repository(self.home / "assistant.db")
        repo.initialize()
        for method_name in (
            "upsert_math_plan_week",
            "add_progress_log",
            "list_math_plan_weeks",
            "latest_progress",
        ):
            self.assertTrue(hasattr(repo, method_name), method_name)
        timezone = ZoneInfo("UTC")
        course = Course(
            "course-demo1001",
            "DEMO1001",
            "Machine Learning for Data Scientists",
            "DEMO-TERM",
            "UTC",
        )
        week = MathPlanWeek(
            "math-demo1001-w1",
            course.id,
            "demo-math-plan",
            1,
            date(2037, 7, 30),
            date(2037, 8, 5),
            "符号识字",
            180,
            "看到讲义公式能念出符号含义",
            date(2037, 9, 16),
            "落后时砍低杠杆练习，不顺延硬截止",
        )
        progress = ProgressLog(
            "progress-demo1001-w1-1",
            50,
            90,
            datetime(2037, 8, 2, 19, 30, tzinfo=timezone),
            math_plan_week_id=week.id,
            note="完成一半",
        )

        repo.upsert_course(course)
        repo.upsert_math_plan_week(week)
        repo.add_progress_log(progress)

        self.assertEqual(repo.list_math_plan_weeks("demo-math-plan"), [week])
        self.assertEqual(repo.latest_progress(math_plan_week_id=week.id), progress)

    def test_replacing_generated_blocks_preserves_completed_and_manual_blocks(self):
        repo = Repository(self.home / "assistant.db")
        repo.initialize()
        for method_name in (
            "upsert_study_block",
            "replace_generated_study_blocks",
            "list_study_blocks",
        ):
            self.assertTrue(hasattr(repo, method_name), method_name)
        timezone = ZoneInfo("UTC")
        course = Course(
            "course-demo1001",
            "DEMO1001",
            "Machine Learning for Data Scientists",
            "DEMO-TERM",
            "UTC",
        )
        assignment = Assignment(
            "assignment-demo1001-a1",
            course.id,
            "Assignment 1",
            "assignment",
            15,
            datetime(2037, 8, 21, 15, 0, tzinfo=timezone),
            date(2037, 7, 29),
        )
        repo.upsert_course(course)
        repo.upsert_assignment(assignment)

        def block(identifier, source, status, start_hour):
            return StudyBlock(
                identifier,
                date(2037, 8, 4),
                time(start_hour, 0),
                time(start_hour + 1, 0),
                identifier,
                "assignment",
                status,
                70,
                source,
                course_id=course.id,
                assignment_id=assignment.id,
                generation_key=identifier,
            )

        old_generated = block("old-generated", "generated", "planned", 13)
        completed = block("completed", "generated", "completed", 14)
        manual = block("manual", "manual", "planned", 15)
        replacement = block("replacement", "generated", "planned", 16)
        for item in (old_generated, completed, manual):
            repo.upsert_study_block(item)

        repo.replace_generated_study_blocks(
            date(2037, 8, 3),
            date(2037, 8, 9),
            [replacement],
        )

        self.assertEqual(
            {item.id for item in repo.list_study_blocks(date(2037, 8, 3), date(2037, 8, 9))},
            {"completed", "manual", "replacement"},
        )

    def test_demo1001_seed_is_idempotent_and_preserves_real_plan_shape(self):
        seed_path = (
            pathlib.Path(__file__).resolve().parents[1]
            / "lib"
            / "study_assistant"
            / "seed_data.py"
        )
        self.assertTrue(seed_path.is_file(), "seed_data.py 必须存在")
        seed_module = importlib.import_module("lib.study_assistant.seed_data")
        repo = Repository(self.home / "assistant.db")
        repo.initialize()

        seed_module.seed_demo(repo)
        seed_module.seed_demo(repo)

        self.assertEqual(len(repo.list_courses()), 4)
        self.assertEqual(len(repo.list_course_sessions()), 7)
        weeks = repo.list_math_plan_weeks("demo-math-plan")
        self.assertEqual(len(weeks), 7)
        self.assertEqual(weeks[0].topic, "符号识字")
        self.assertEqual(weeks[-1].topic, "真题全真演练与补漏")
        self.assertTrue(all(week.hard_deadline == date(2037, 9, 16) for week in weeks))
        math_blocks = [
            block
            for block in repo.list_study_blocks()
            if block.block_type == "math" and block.source == "seed"
        ]
        self.assertEqual(len(math_blocks), 16)
        assignments = repo.list_active_assignments()
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0].title, "Assignment 1")
        self.assertEqual(
            [
                reminder.target_percent
                for reminder in repo.list_deadline_reminders(assignments[0].id)
            ],
            [0, 25, 50, 75, 90, 100],
        )


if __name__ == "__main__":
    unittest.main()
