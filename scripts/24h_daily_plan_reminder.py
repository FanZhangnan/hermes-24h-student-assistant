#!/usr/bin/env python3
import pathlib
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo


LIB = pathlib.Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

from study_assistant.paths import RuntimePaths
from study_assistant.repository import Repository
from study_assistant.i18n import configure_utf8_output


def render_today(repository, today):
    courses = {course.id: course for course in repository.list_courses()}
    assignments = {
        assignment.id: assignment for assignment in repository.list_active_assignments()
    }
    blocks = repository.list_study_blocks(today, today)
    reminders = [
        reminder
        for reminder in repository.list_deadline_reminders()
        if reminder.status == "pending" and reminder.remind_at.date() == today
    ]

    lines = ["【今日学业计划｜{}】".format(today.isoformat())]
    if blocks:
        for index, block in enumerate(blocks, start=1):
            course = courses.get(block.course_id)
            course_code = course.code if course else "未指定课程"
            compressed = "【压缩】" if block.compressed else ""
            lines.append(
                "{}. {}-{} {} · {}{}".format(
                    index,
                    block.start_time.isoformat(timespec="minutes"),
                    block.end_time.isoformat(timespec="minutes"),
                    course_code,
                    compressed,
                    block.title,
                )
            )
            if block.note:
                lines.append("   {}".format(block.note))
    else:
        lines.append("今天没有已安排的学习时间块。")

    if reminders:
        lines.append("")
        lines.append("【今日里程碑】")
        for reminder in reminders:
            assignment = assignments.get(reminder.assignment_id)
            course = courses.get(assignment.course_id) if assignment else None
            course_code = course.code if course else "未指定课程"
            target = (
                "{}% · ".format(reminder.target_percent)
                if reminder.target_percent is not None
                else ""
            )
            lines.append("- {} · {}{}".format(course_code, target, reminder.message))

    lines.append("")
    lines.append(
        "执行规则：落后压缩、不顺延；所有补量必须留在原截止日前。"
    )
    return "\n".join(lines)


def main(today=None):
    paths = RuntimePaths.from_environment()
    if not paths.database.is_file():
        print("学业雷达数据库尚未初始化；请先运行 24h_assistant.py init。")
        return 1
    repository = Repository(paths.database)
    profile = repository.get_profile()
    if today is None:
        if profile:
            today = datetime.now(ZoneInfo(profile.timezone)).date()
        else:
            today = date.today()
    print(render_today(repository, today))
    return 0


if __name__ == "__main__":
    configure_utf8_output()
    raise SystemExit(main())
