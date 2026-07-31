import importlib
import pathlib
import unittest
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from lib.study_assistant.models import Assignment, CourseSession


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLANNER_PATH = ROOT / "lib" / "study_assistant" / "study_planner.py"


def load_planner_module(test_case):
    test_case.assertTrue(PLANNER_PATH.is_file(), "study_planner.py 必须存在")
    return importlib.import_module("lib.study_assistant.study_planner")


class StudyPlannerTest(unittest.TestCase):
    def setUp(self):
        self.timezone = ZoneInfo("UTC")

    def assignment(self, identifier, weight, due, start=None):
        return Assignment(
            identifier,
            "course-demo1001",
            identifier,
            "assignment",
            weight,
            datetime.combine(due, time(15, 0), self.timezone),
            start or due,
        )

    def test_milestone_start_lead_depends_on_weight_and_honours_explicit_start(self):
        planner_module = load_planner_module(self)
        planner = planner_module.StudyPlanner("UTC")
        due = date(2037, 8, 21)

        normal = planner.milestones_for_assignment(self.assignment("normal", 15, due))
        high = planner.milestones_for_assignment(self.assignment("high", 30, due))
        critical = planner.milestones_for_assignment(self.assignment("critical", 50, due))
        explicit = planner.milestones_for_assignment(
            self.assignment("explicit", 15, due, date(2037, 7, 29))
        )

        self.assertEqual(normal[0].on_date, date(2037, 8, 7))
        self.assertEqual(high[0].on_date, date(2037, 7, 31))
        self.assertEqual(critical[0].on_date, date(2037, 7, 24))
        self.assertEqual(explicit[0].on_date, date(2037, 7, 29))
        for milestones in (normal, high, critical, explicit):
            self.assertEqual(
                [item.target_percent for item in milestones],
                [0, 25, 50, 75, 90, 100],
            )
            self.assertTrue(all(item.on_date <= due for item in milestones))

    def test_generate_week_avoids_classes_and_quiet_hours(self):
        planner_module = load_planner_module(self)
        planner = planner_module.StudyPlanner("UTC")
        assignment = self.assignment(
            "assignment-demo1001-a1",
            15,
            date(2037, 8, 21),
            date(2037, 7, 29),
        )
        monday_class = CourseSession(
            "session-monday",
            assignment.course_id,
            0,
            time(15, 30),
            time(17, 30),
            valid_from=date(2037, 7, 27),
            valid_to=date(2037, 10, 30),
        )

        result = planner.generate_week(
            date(2037, 8, 3),
            [assignment],
            [monday_class],
            {assignment.id: 0},
        )

        self.assertTrue(result.blocks)
        for block in result.blocks:
            self.assertGreaterEqual(block.start_time, time(7, 0))
            self.assertLessEqual(block.end_time, time(22, 30))
            if block.block_date == date(2037, 8, 3):
                self.assertTrue(
                    block.end_time <= monday_class.start_time
                    or block.start_time >= monday_class.end_time
                )

    def test_behind_schedule_compresses_before_original_deadline(self):
        planner_module = load_planner_module(self)
        planner = planner_module.StudyPlanner("UTC")
        assignment = self.assignment(
            "assignment-due-wednesday",
            40,
            date(2037, 8, 5),
            date(2037, 7, 15),
        )

        result = planner.generate_week(
            date(2037, 8, 3),
            [assignment],
            [],
            {assignment.id: 10},
        )

        assignment_blocks = [
            block for block in result.blocks if block.assignment_id == assignment.id
        ]
        self.assertTrue(assignment_blocks)
        self.assertTrue(result.compressed)
        self.assertTrue(all(block.compressed for block in assignment_blocks))
        self.assertTrue(
            all(block.block_date <= assignment.due_at.date() for block in assignment_blocks)
        )
        due_day_blocks = [
            block
            for block in assignment_blocks
            if block.block_date == assignment.due_at.date()
        ]
        self.assertTrue(all(block.end_time <= time(15, 0) for block in due_day_blocks))

    def test_behind_schedule_uses_more_capacity_than_on_track_work(self):
        planner_module = load_planner_module(self)
        planner = planner_module.StudyPlanner("UTC")
        assignment = self.assignment(
            "assignment-capacity",
            40,
            date(2037, 8, 21),
            date(2037, 7, 15),
        )

        on_track = planner.generate_week(
            date(2037, 8, 3),
            [assignment],
            [],
            {assignment.id: 75},
        )
        behind = planner.generate_week(
            date(2037, 8, 3),
            [assignment],
            [],
            {assignment.id: 10},
        )

        self.assertFalse(on_track.compressed)
        self.assertTrue(behind.compressed)
        self.assertGreater(len(behind.blocks), len(on_track.blocks))
        self.assertTrue(
            all(block.block_date <= assignment.due_at.date() for block in behind.blocks)
        )

    def test_daytime_quiet_period_is_removed_from_candidate_windows(self):
        planner_module = load_planner_module(self)
        planner = planner_module.StudyPlanner(
            "UTC",
            quiet_start=time(13, 0),
            quiet_end=time(17, 0),
        )
        assignment = self.assignment(
            "assignment-quiet",
            15,
            date(2037, 8, 21),
            date(2037, 8, 3),
        )

        result = planner.generate_week(
            date(2037, 8, 3),
            [assignment],
            [],
            {assignment.id: 0},
        )

        self.assertTrue(result.blocks)
        for block in result.blocks:
            self.assertTrue(block.end_time <= time(13, 0) or block.start_time >= time(17, 0))

    def test_generated_blocks_do_not_exceed_remaining_estimated_minutes(self):
        planner_module = load_planner_module(self)
        planner = planner_module.StudyPlanner("UTC")
        assignment = self.assignment(
            "assignment-bounded",
            40,
            date(2037, 8, 21),
            date(2037, 7, 15),
        )

        result = planner.generate_week(
            date(2037, 8, 3),
            [assignment],
            [],
            {assignment.id: 25},
        )

        planned_minutes = sum(
            (block.end_time.hour * 60 + block.end_time.minute)
            - (block.start_time.hour * 60 + block.start_time.minute)
            for block in result.blocks
        )
        remaining_estimate = int(assignment.estimated_minutes * 0.75)
        self.assertEqual(planned_minutes, remaining_estimate)


if __name__ == "__main__":
    unittest.main()
