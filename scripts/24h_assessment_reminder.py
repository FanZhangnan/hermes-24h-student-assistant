#!/usr/bin/env python3
"""从结构化学业雷达数据库生成作业与里程碑提醒。"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


LIB = pathlib.Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

from study_assistant.paths import RuntimePaths  # noqa: E402
from study_assistant.repository import Repository  # noqa: E402
from study_assistant.i18n import configure_utf8_output  # noqa: E402


ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "courses" / "assessment_reminder_state.json"
TIMEZONE = "UTC"


def _load_state(path):
    if not path.is_file():
        return {"sent": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sent": {}}


def _save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _in_quiet_hours(now):
    minutes = now.hour * 60 + now.minute
    return minutes >= 22 * 60 + 30 or minutes < 7 * 60


def _expected_progress(repository, assignment, today):
    reminders = [
        reminder
        for reminder in repository.list_deadline_reminders(assignment.id)
        if reminder.target_percent is not None and reminder.remind_at.date() <= today
    ]
    if not reminders:
        return 0, "阅读要求并拆解任务"
    current = max(reminders, key=lambda reminder: reminder.remind_at)
    return current.target_percent, current.message


def _course_codes(repository):
    return {course.id: course.code for course in repository.list_courses()}


def _render_morning_digest(repository, today):
    courses = _course_codes(repository)
    active = [
        assignment
        for assignment in repository.list_active_assignments(through=today)
        if assignment.start_date <= today <= assignment.due_at.date()
    ]
    lines = ["【今日学业计划｜{}】".format(today.isoformat())]
    if not active:
        lines.append("今天没有进行中的硬截止任务，可用于预习或补笔记。")
    else:
        lines.append("进行中任务（按截止时间）：")
        for assignment in active[:5]:
            progress, action = _expected_progress(repository, assignment, today)
            remaining = (assignment.due_at.date() - today).days
            lines.append(
                "- [{}] {}｜剩 {} 天｜建议进度至少 {}%".format(
                    courses.get(assignment.course_id, "未指定课程"),
                    assignment.title,
                    remaining,
                    progress,
                )
            )
            lines.append("  当前行动：{}".format(action))
    return lines


def main(now=None, state_path=None):
    paths = RuntimePaths.from_environment()
    if not paths.database.is_file():
        return 0
    repository = Repository(paths.database)
    profile = repository.get_profile()
    timezone = ZoneInfo(profile.timezone if profile else TIMEZONE)
    now = now or datetime.now(timezone)
    if _in_quiet_hours(now):
        return 0

    today = now.date()
    state_path = pathlib.Path(state_path) if state_path else STATE_PATH
    state = _load_state(state_path)
    sent = state.setdefault("sent", {})
    cutoff = (today - timedelta(days=21)).isoformat()
    sent = {key: value for key, value in sent.items() if value >= cutoff}
    state["sent"] = sent
    lines = []

    digest_key = "digest:{}".format(today.isoformat())
    if 8 <= now.hour < 9 and digest_key not in sent:
        lines.extend(_render_morning_digest(repository, today))
        sent[digest_key] = today.isoformat()

    courses = _course_codes(repository)
    assignments = {
        assignment.id: assignment for assignment in repository.list_active_assignments()
    }
    for reminder in repository.list_deadline_reminders():
        if reminder.status != "pending" or reminder.remind_at.date() != today:
            continue
        key = "milestone:{}".format(reminder.id)
        if key in sent:
            continue
        assignment = assignments.get(reminder.assignment_id)
        if assignment is None:
            continue
        lines.append(
            "【今日里程碑】\n[{}] {}｜目标 {}%\n{}".format(
                courses.get(assignment.course_id, "未指定课程"),
                assignment.title,
                reminder.target_percent if reminder.target_percent is not None else "未设定",
                reminder.message,
            )
        )
        sent[key] = today.isoformat()

    for assignment in assignments.values():
        days_left = (assignment.due_at.date() - today).days
        if days_left not in {7, 3, 1, 0}:
            continue
        if days_left > 0 and not 8 <= now.hour < 10:
            continue
        if days_left == 0 and not (8 <= now.hour < 10 or 12 <= now.hour < 14):
            continue
        key = "due:{}:{}:{}".format(assignment.id, days_left, today.isoformat())
        if key in sent:
            continue
        progress, action = _expected_progress(repository, assignment, today)
        label = {7: "还有 7 天", 3: "还有 3 天", 1: "明天截止", 0: "今天截止"}[
            days_left
        ]
        lines.append(
            "【截止提醒｜{}】\n[{}] {}（{}%）\n截止：{}\n建议进度至少 {}%｜{}".format(
                label,
                courses.get(assignment.course_id, "未指定课程"),
                assignment.title,
                assignment.weight,
                assignment.due_at.strftime("%Y-%m-%d %H:%M"),
                progress,
                action,
            )
        )
        sent[key] = today.isoformat()

    _save_state(state_path, state)
    if lines:
        lines.append("执行规则：落后压缩、不顺延；所有补量必须留在原截止日前。")
        print("\n\n".join(lines))
    return 0


if __name__ == "__main__":
    configure_utf8_output()
    raise SystemExit(main())
