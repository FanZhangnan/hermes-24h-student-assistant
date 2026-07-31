#!/usr/bin/env python3
"""从结构化数据库生成通用数学计划提醒。"""
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


ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "courses" / "math_plan_reminder_state.json"
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

    courses = {course.id: course.code for course in repository.list_courses()}
    weeks = {week.id: week for week in repository.list_math_plan_weeks()}
    blocks = [
        block
        for block in repository.list_study_blocks(today, today)
        if block.block_type == "math" and block.status == "planned"
    ]
    lines = []
    for block in blocks:
        start = datetime.combine(today, block.start_time, timezone)
        minutes_to_start = (start - now).total_seconds() / 60
        slot = None
        if 8 <= now.hour < 9:
            slot = "morning"
        elif 0 <= minutes_to_start <= 90:
            slot = "lead"
        if slot is None:
            continue
        key = "mathsess:{}:{}:{}".format(
            today.isoformat(), block.start_time.isoformat(timespec="minutes"), slot
        )
        if key in sent:
            continue
        week = weeks.get(block.math_plan_week_id)
        lines.append(block.title)
        lines.append(
            "今日 {}-{}：{}".format(
                block.start_time.isoformat(timespec="minutes"),
                block.end_time.isoformat(timespec="minutes"),
                block.note or "按计划完成本次学习块",
            )
        )
        if week is not None:
            lines.append("完成标准：{}".format(week.done_criteria))
            lines.append("硬截止：{}；落后压缩、不顺延。".format(week.hard_deadline))
        sent[key] = today.isoformat()

    _save_state(state_path, state)
    if lines:
        course_code = courses.get(blocks[0].course_id, "数学计划")
        print("【{} 执行计划】".format(course_code))
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
