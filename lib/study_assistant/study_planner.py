from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Dict, Iterable, List, Sequence, Tuple
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from .models import Assignment, CourseSession, StudyBlock


@dataclass(frozen=True)
class Milestone:
    on_date: date
    target_percent: int
    action: str


@dataclass(frozen=True)
class GeneratedWeek:
    week_start: date
    week_end: date
    blocks: Tuple[StudyBlock, ...]
    compressed: bool


DEFAULT_WINDOWS = {
    0: ((time(15, 30), time(17, 30)), (time(19, 30), time(21, 30))),
    1: ((time(13, 0), time(16, 0)), (time(19, 30), time(21, 30))),
    2: ((time(14, 0), time(17, 0)), (time(19, 30), time(21, 0))),
    3: ((time(13, 0), time(16, 30)), (time(19, 30), time(21, 30))),
    4: ((time(13, 0), time(16, 0)), (time(19, 0), time(20, 30))),
    5: ((time(9, 30), time(12, 0)), (time(14, 0), time(17, 0))),
    6: ((time(9, 30), time(12, 0)), (time(14, 0), time(17, 0))),
}


MILESTONE_ACTIONS = (
    "开工：读懂要求和评分标准，列出任务拆解",
    "完成资料收集、数据探索和框架搭建",
    "完成主体分析或核心实现",
    "完成初稿主体，确保主路径可运行",
    "完整初稿冻结，进入检查、润色和测试",
    "提交前最终检查并完成上传",
)


def _minutes(value):
    return value.hour * 60 + value.minute


def _clock(value):
    return time(value // 60, value % 60)


def _subtract_busy(windows, busy_start, busy_end):
    result = []
    busy_start_min = _minutes(busy_start)
    busy_end_min = _minutes(busy_end)
    for start, end in windows:
        start_min = _minutes(start)
        end_min = _minutes(end)
        if busy_end_min <= start_min or busy_start_min >= end_min:
            result.append((start, end))
            continue
        if busy_start_min - start_min >= 30:
            result.append((start, _clock(busy_start_min)))
        if end_min - busy_end_min >= 30:
            result.append((_clock(busy_end_min), end))
    return result


class StudyPlanner:
    def __init__(
        self,
        timezone_name,
        quiet_start=time(22, 30),
        quiet_end=time(7, 0),
    ):
        self.timezone = ZoneInfo(timezone_name)
        self.quiet_start = quiet_start
        self.quiet_end = quiet_end

    @staticmethod
    def _lead_days(weight):
        if weight >= 50:
            return 28
        if weight >= 30:
            return 21
        return 14

    def milestones_for_assignment(self, assignment):
        due_date = assignment.due_at.astimezone(self.timezone).date()
        default_start = due_date - timedelta(days=self._lead_days(assignment.weight))
        if assignment.start_date < due_date:
            start = assignment.start_date
        else:
            start = default_start
        if start > due_date:
            raise ValueError("作业开工日期不能晚于截止日期")

        review_buffer = 4 if assignment.weight >= 50 else 3 if assignment.weight >= 30 else 2
        review_date = max(start, due_date - timedelta(days=review_buffer))
        span = max((review_date - start).days, 1)
        dates = (
            start,
            min(review_date, start + timedelta(days=max(1, span // 4))),
            min(review_date, start + timedelta(days=max(2, span // 2))),
            min(review_date, start + timedelta(days=max(3, span * 3 // 4))),
            review_date,
            due_date,
        )
        return tuple(
            Milestone(on_date, percent, action)
            for on_date, percent, action in zip(
                dates,
                (0, 25, 50, 75, 90, 100),
                MILESTONE_ACTIONS,
            )
        )

    def _expected_percent(self, assignment, on_date):
        expected = 0
        for milestone in self.milestones_for_assignment(assignment):
            if milestone.on_date <= on_date:
                expected = milestone.target_percent
        return expected

    def _priority(self, assignment, on_date, compressed):
        days_left = max((assignment.due_at.date() - on_date).days, 0)
        urgency = max(0, 20 - days_left)
        compression_bonus = 15 if compressed else 0
        return min(100, int(35 + assignment.weight + urgency + compression_bonus))

    def _day_windows(self, on_date, sessions):
        windows = list(DEFAULT_WINDOWS[on_date.weekday()])
        for session in sessions:
            if not session.confirmed or session.weekday != on_date.weekday():
                continue
            if session.valid_from and on_date < session.valid_from:
                continue
            if session.valid_to and on_date > session.valid_to:
                continue
            windows = _subtract_busy(windows, session.start_time, session.end_time)

        if self.quiet_start > self.quiet_end:
            allowed_start = _minutes(self.quiet_end)
            allowed_end = _minutes(self.quiet_start)
            clipped = []
            for start, end in windows:
                start_min = max(_minutes(start), allowed_start)
                end_min = min(_minutes(end), allowed_end)
                if end_min - start_min >= 30:
                    clipped.append((_clock(start_min), _clock(end_min)))
            windows = clipped
        elif self.quiet_start < self.quiet_end:
            windows = _subtract_busy(windows, self.quiet_start, self.quiet_end)
        return windows

    def generate_week(
        self,
        week_start,
        assignments: Sequence[Assignment],
        sessions: Sequence[CourseSession],
        progress_by_assignment: Dict[str, int],
    ):
        if week_start.weekday() != 0:
            raise ValueError("周计划必须从星期一开始")
        week_end = week_start + timedelta(days=6)
        blocks: List[StudyBlock] = []
        remaining_minutes = {
            assignment.id: int(
                assignment.estimated_minutes
                * (100 - progress_by_assignment.get(assignment.id, 0))
                / 100
            )
            for assignment in assignments
        }

        for offset in range(7):
            on_date = week_start + timedelta(days=offset)
            active = []
            for assignment in assignments:
                due_local = assignment.due_at.astimezone(self.timezone)
                due_date = due_local.date()
                if assignment.status == "submitted":
                    continue
                if remaining_minutes[assignment.id] <= 0:
                    continue
                if not (assignment.start_date <= on_date <= due_date):
                    continue
                expected = self._expected_percent(assignment, on_date)
                actual = progress_by_assignment.get(assignment.id, 0)
                compressed = actual < expected
                active.append((assignment, compressed, due_local))
            active.sort(key=lambda item: (item[2], -item[0].weight, item[0].id))
            active = active[:3]
            if not active:
                continue

            windows = self._day_windows(on_date, sessions)
            compressed_tasks = [item for item in active if item[1]]
            for index, (start, end) in enumerate(windows):
                if index < len(active):
                    assignment, compressed, due_local = active[index]
                elif compressed_tasks:
                    available_compressed = [
                        item
                        for item in compressed_tasks
                        if remaining_minutes[item[0].id] > 0
                    ]
                    if not available_compressed:
                        break
                    assignment, compressed, due_local = available_compressed[
                        (index - len(active)) % len(available_compressed)
                    ]
                else:
                    break
                if remaining_minutes[assignment.id] <= 0:
                    continue
                if on_date == due_local.date():
                    if start >= due_local.timetz().replace(tzinfo=None):
                        continue
                    end = min(end, due_local.timetz().replace(tzinfo=None))
                    if _minutes(end) - _minutes(start) < 30:
                        continue
                available_minutes = _minutes(end) - _minutes(start)
                allocated_minutes = min(
                    available_minutes,
                    remaining_minutes[assignment.id],
                )
                if allocated_minutes <= 0:
                    continue
                end = _clock(_minutes(start) + allocated_minutes)
                remaining_minutes[assignment.id] -= allocated_minutes
                generation_key = "{}:{}:{}:{}".format(
                    week_start.isoformat(),
                    assignment.id,
                    on_date.isoformat(),
                    start.isoformat(timespec="minutes"),
                )
                next_milestone = next(
                    (
                        item
                        for item in self.milestones_for_assignment(assignment)
                        if item.on_date >= on_date
                    ),
                    None,
                )
                note = None
                if next_milestone:
                    note = "目标 {}%：{}".format(
                        next_milestone.target_percent,
                        next_milestone.action,
                    )
                if compressed:
                    note = "压缩执行；" + (note or "优先完成截止日前剩余工作")
                blocks.append(
                    StudyBlock(
                        "block-" + uuid5(NAMESPACE_URL, generation_key).hex,
                        on_date,
                        start,
                        end,
                        assignment.title,
                        "assignment",
                        "planned",
                        self._priority(assignment, on_date, compressed),
                        "generated",
                        course_id=assignment.course_id,
                        assignment_id=assignment.id,
                        generation_key=generation_key,
                        note=note,
                        compressed=compressed,
                    )
                )

        return GeneratedWeek(
            week_start,
            week_end,
            tuple(blocks),
            any(block.compressed for block in blocks),
        )
