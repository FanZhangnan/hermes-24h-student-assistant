from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional


@dataclass(frozen=True)
class StudentProfile:
    school: str
    campus: str
    city: str
    timezone: str
    language: str = "zh-CN"
    degree: Optional[str] = None
    major: Optional[str] = None


@dataclass(frozen=True)
class DeliveryTarget:
    platform: str
    target: str


@dataclass(frozen=True)
class Course:
    id: str
    code: str
    title: str
    term: str
    timezone: str
    profile_url: Optional[str] = None


@dataclass(frozen=True)
class CourseSession:
    id: str
    course_id: str
    weekday: int
    start_time: time
    end_time: time
    location: Optional[str] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    source_uid: Optional[str] = None
    confirmed: bool = True


@dataclass(frozen=True)
class Assignment:
    id: str
    course_id: str
    title: str
    kind: str
    weight: float
    due_at: datetime
    start_date: date
    status: str = "pending"
    estimated_minutes: int = 600


@dataclass(frozen=True)
class StudyBlock:
    id: str
    block_date: date
    start_time: time
    end_time: time
    title: str
    block_type: str
    status: str
    priority: int
    source: str
    course_id: Optional[str] = None
    assignment_id: Optional[str] = None
    math_plan_week_id: Optional[str] = None
    generation_key: Optional[str] = None
    note: Optional[str] = None
    compressed: bool = False


@dataclass(frozen=True)
class MathPlanWeek:
    id: str
    course_id: str
    plan_key: str
    week_number: int
    start_date: date
    end_date: date
    topic: str
    target_minutes: int
    done_criteria: str
    hard_deadline: date
    compression_policy: str
    status: str = "pending"


@dataclass(frozen=True)
class ProgressLog:
    id: str
    percent: int
    minutes: int
    logged_at: datetime
    assignment_id: Optional[str] = None
    math_plan_week_id: Optional[str] = None
    note: Optional[str] = None


@dataclass(frozen=True)
class DeadlineReminder:
    id: str
    assignment_id: str
    remind_at: datetime
    reminder_type: str
    message: str
    status: str = "pending"
    target_percent: Optional[int] = None
    sent_at: Optional[datetime] = None
