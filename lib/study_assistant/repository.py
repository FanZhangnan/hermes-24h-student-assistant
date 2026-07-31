import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import (
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


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS student_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    school TEXT NOT NULL,
    campus TEXT NOT NULL,
    city TEXT NOT NULL,
    timezone TEXT NOT NULL,
    language TEXT NOT NULL,
    degree TEXT,
    major TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS module_consent (
    module TEXT PRIMARY KEY,
    granted INTEGER NOT NULL CHECK (granted IN (0, 1)),
    policy_version TEXT NOT NULL,
    granted_at TEXT,
    revoked_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminder_policy (
    event_type TEXT PRIMARY KEY,
    lead_minutes INTEGER NOT NULL CHECK (lead_minutes >= 0),
    quiet_start TEXT NOT NULL,
    quiet_end TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS delivery_target (
    platform TEXT NOT NULL,
    target TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 1 CHECK (is_primary IN (0, 1)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (platform, target)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_primary_delivery
ON delivery_target(is_primary) WHERE is_primary = 1;
CREATE TABLE IF NOT EXISTS reminder_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reminder_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('complete', 'later', 'useless')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS managed_cron_job (
    job_id TEXT PRIMARY KEY,
    purpose TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    term TEXT NOT NULL,
    timezone TEXT NOT NULL,
    profile_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(code, term)
);
CREATE TABLE IF NOT EXISTS course_sessions (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    location TEXT,
    valid_from TEXT,
    valid_to TEXT,
    source_uid TEXT UNIQUE,
    confirmed INTEGER NOT NULL DEFAULT 1 CHECK (confirmed IN (0, 1)),
    CHECK (start_time < end_time)
);
CREATE TABLE IF NOT EXISTS assignments (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'assignment',
    weight REAL NOT NULL CHECK (weight BETWEEN 0 AND 100),
    due_at TEXT NOT NULL,
    start_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'submitted')),
    estimated_minutes INTEGER NOT NULL DEFAULT 600 CHECK (estimated_minutes > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(course_id, title, due_at)
);
CREATE TABLE IF NOT EXISTS math_plan_weeks (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    plan_key TEXT NOT NULL,
    week_number INTEGER NOT NULL CHECK (week_number > 0),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    topic TEXT NOT NULL,
    target_minutes INTEGER NOT NULL CHECK (target_minutes > 0),
    done_criteria TEXT NOT NULL,
    hard_deadline TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'completed')),
    compression_policy TEXT NOT NULL,
    UNIQUE(plan_key, week_number),
    CHECK (start_date <= end_date),
    CHECK (end_date <= hard_deadline)
);
CREATE TABLE IF NOT EXISTS study_blocks (
    id TEXT PRIMARY KEY,
    course_id TEXT REFERENCES courses(id) ON DELETE CASCADE,
    assignment_id TEXT REFERENCES assignments(id) ON DELETE CASCADE,
    math_plan_week_id TEXT REFERENCES math_plan_weeks(id) ON DELETE CASCADE,
    block_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    title TEXT NOT NULL,
    block_type TEXT NOT NULL
        CHECK (block_type IN ('assignment', 'math', 'review', 'milestone')),
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'completed', 'skipped')),
    priority INTEGER NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
    source TEXT NOT NULL CHECK (source IN ('generated', 'seed', 'manual')),
    generation_key TEXT UNIQUE,
    note TEXT,
    compressed INTEGER NOT NULL DEFAULT 0 CHECK (compressed IN (0, 1)),
    created_at TEXT NOT NULL,
    CHECK (start_time < end_time),
    CHECK (assignment_id IS NOT NULL OR math_plan_week_id IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS progress_logs (
    id TEXT PRIMARY KEY,
    assignment_id TEXT REFERENCES assignments(id) ON DELETE CASCADE,
    math_plan_week_id TEXT REFERENCES math_plan_weeks(id) ON DELETE CASCADE,
    percent INTEGER NOT NULL CHECK (percent BETWEEN 0 AND 100),
    minutes INTEGER NOT NULL DEFAULT 0 CHECK (minutes >= 0),
    note TEXT,
    logged_at TEXT NOT NULL,
    CHECK ((assignment_id IS NOT NULL) <> (math_plan_week_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS deadline_reminders (
    id TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    remind_at TEXT NOT NULL,
    reminder_type TEXT NOT NULL,
    target_percent INTEGER CHECK (target_percent BETWEEN 0 AND 100),
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sent', 'cancelled')),
    sent_at TEXT,
    UNIQUE(assignment_id, reminder_type, remind_at)
);
CREATE INDEX IF NOT EXISTS assignments_status_due
ON assignments(status, due_at);
CREATE INDEX IF NOT EXISTS course_sessions_weekday_range
ON course_sessions(weekday, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS study_blocks_date_status
ON study_blocks(block_date, status);
CREATE INDEX IF NOT EXISTS progress_assignment_time
ON progress_logs(assignment_id, logged_at);
CREATE INDEX IF NOT EXISTS progress_math_week_time
ON progress_logs(math_plan_week_id, logged_at);
CREATE INDEX IF NOT EXISTS math_plan_date_status
ON math_plan_weeks(start_date, end_date, status);
CREATE INDEX IF NOT EXISTS reminders_status_time
ON deadline_reminders(status, remind_at);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _date(value):
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def _time(value):
    return datetime.strptime(value, "%H:%M").time() if value else None


def _datetime(value):
    return datetime.fromisoformat(value) if value else None


def _date_text(value):
    return value.isoformat() if value else None


def _time_text(value):
    return value.isoformat(timespec="minutes") if value else None


def _datetime_text(value):
    return value.isoformat() if value else None


def _course_from_row(row):
    return Course(
        row["id"],
        row["code"],
        row["title"],
        row["term"],
        row["timezone"],
        row["profile_url"],
    )


def _course_session_from_row(row):
    return CourseSession(
        row["id"],
        row["course_id"],
        row["weekday"],
        _time(row["start_time"]),
        _time(row["end_time"]),
        row["location"],
        _date(row["valid_from"]),
        _date(row["valid_to"]),
        row["source_uid"],
        bool(row["confirmed"]),
    )


def _assignment_from_row(row):
    return Assignment(
        row["id"],
        row["course_id"],
        row["title"],
        row["kind"],
        row["weight"],
        _datetime(row["due_at"]),
        _date(row["start_date"]),
        row["status"],
        row["estimated_minutes"],
    )


def _math_plan_week_from_row(row):
    return MathPlanWeek(
        row["id"],
        row["course_id"],
        row["plan_key"],
        row["week_number"],
        _date(row["start_date"]),
        _date(row["end_date"]),
        row["topic"],
        row["target_minutes"],
        row["done_criteria"],
        _date(row["hard_deadline"]),
        row["compression_policy"],
        row["status"],
    )


def _study_block_from_row(row):
    return StudyBlock(
        row["id"],
        _date(row["block_date"]),
        _time(row["start_time"]),
        _time(row["end_time"]),
        row["title"],
        row["block_type"],
        row["status"],
        row["priority"],
        row["source"],
        row["course_id"],
        row["assignment_id"],
        row["math_plan_week_id"],
        row["generation_key"],
        row["note"],
        bool(row["compressed"]),
    )


def _progress_log_from_row(row):
    return ProgressLog(
        row["id"],
        row["percent"],
        row["minutes"],
        _datetime(row["logged_at"]),
        row["assignment_id"],
        row["math_plan_week_id"],
        row["note"],
    )


def _deadline_reminder_from_row(row):
    return DeadlineReminder(
        row["id"],
        row["assignment_id"],
        _datetime(row["remind_at"]),
        row["reminder_type"],
        row["message"],
        row["status"],
        row["target_percent"],
        _datetime(row["sent_at"]),
    )


class Repository:
    def __init__(self, database):
        self.database = Path(database)

    def _connect(self):
        connection = sqlite3.connect(str(self.database))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.database.parent.chmod(0o700)

        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                "VALUES (?, ?)",
                (1, _now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                "VALUES (?, ?)",
                (2, _now()),
            )

        if os.name != "nt":
            self.database.chmod(0o600)

    def save_profile(self, profile):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO student_profile
                    (id, school, campus, city, timezone, language, degree, major, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    school=excluded.school,
                    campus=excluded.campus,
                    city=excluded.city,
                    timezone=excluded.timezone,
                    language=excluded.language,
                    degree=excluded.degree,
                    major=excluded.major,
                    updated_at=excluded.updated_at
                """,
                (
                    profile.school,
                    profile.campus,
                    profile.city,
                    profile.timezone,
                    profile.language,
                    profile.degree,
                    profile.major,
                    _now(),
                ),
            )

    def get_profile(self):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT school, campus, city, timezone, language, degree, major "
                "FROM student_profile WHERE id = 1"
            ).fetchone()
        return StudentProfile(**dict(row)) if row else None

    def set_consent(self, module, granted, policy_version):
        now = _now()
        with self._connect() as connection:
            current = connection.execute(
                "SELECT granted_at, revoked_at FROM module_consent WHERE module = ?",
                (module,),
            ).fetchone()
            if granted:
                granted_at = current["granted_at"] if current else None
                granted_at = granted_at or now
                revoked_at = None
            else:
                granted_at = current["granted_at"] if current else None
                revoked_at = current["revoked_at"] if current else None
                revoked_at = revoked_at or now

            connection.execute(
                """
                INSERT INTO module_consent
                    (module, granted, policy_version, granted_at, revoked_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(module) DO UPDATE SET
                    granted=excluded.granted,
                    policy_version=excluded.policy_version,
                    granted_at=excluded.granted_at,
                    revoked_at=excluded.revoked_at,
                    updated_at=excluded.updated_at
                """,
                (
                    module,
                    int(granted),
                    policy_version,
                    granted_at,
                    revoked_at,
                    now,
                ),
            )

    def list_consents(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT module, granted FROM module_consent"
            ).fetchall()
        return {row["module"]: bool(row["granted"]) for row in rows}

    def set_primary_delivery(self, delivery):
        with self._connect() as connection:
            connection.execute("UPDATE delivery_target SET is_primary = 0")
            connection.execute(
                """
                INSERT INTO delivery_target(platform, target, is_primary, created_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(platform, target) DO UPDATE SET is_primary = 1
                """,
                (delivery.platform, delivery.target, _now()),
            )

    def get_primary_delivery(self):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT platform, target FROM delivery_target WHERE is_primary = 1"
            ).fetchone()
        return DeliveryTarget(**dict(row)) if row else None

    def set_policy(self, event_type, lead_minutes, quiet_start, quiet_end):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reminder_policy
                    (event_type, lead_minutes, quiet_start, quiet_end, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_type) DO UPDATE SET
                    lead_minutes=excluded.lead_minutes,
                    quiet_start=excluded.quiet_start,
                    quiet_end=excluded.quiet_end,
                    updated_at=excluded.updated_at
                """,
                (event_type, lead_minutes, quiet_start, quiet_end, _now()),
            )

    def record_feedback(self, reminder_id, action):
        if action not in {"complete", "later", "useless"}:
            raise ValueError("action 必须是 complete、later 或 useless")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO reminder_feedback(reminder_id, action, created_at) "
                "VALUES (?, ?, ?)",
                (reminder_id, action, _now()),
            )

    def register_cron_job(self, job_id, purpose):
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO managed_cron_job(job_id, purpose, created_at) "
                "VALUES (?, ?, ?)",
                (job_id, purpose, _now()),
            )

    def list_managed_cron_jobs(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT job_id, purpose FROM managed_cron_job ORDER BY job_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_managed_cron_job(self, job_id):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM managed_cron_job WHERE job_id = ?",
                (job_id,),
            )

    def upsert_course(self, course):
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO courses(
                    id, code, title, term, timezone, profile_url, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code, term) DO UPDATE SET
                    title=excluded.title,
                    timezone=excluded.timezone,
                    profile_url=excluded.profile_url,
                    updated_at=excluded.updated_at
                """,
                (
                    course.id,
                    course.code,
                    course.title,
                    course.term,
                    course.timezone,
                    course.profile_url,
                    now,
                    now,
                ),
            )
        return self.get_course_by_code(course.code, course.term)

    def get_course_by_code(self, code, term=None):
        query = "SELECT * FROM courses WHERE code = ?"
        parameters = [code]
        if term is not None:
            query += " AND term = ?"
            parameters.append(term)
        query += " ORDER BY term DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        return _course_from_row(row) if row else None

    def list_courses(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM courses ORDER BY term, code"
            ).fetchall()
        return [_course_from_row(row) for row in rows]

    def upsert_course_session(self, session):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO course_sessions(
                    id, course_id, weekday, start_time, end_time, location,
                    valid_from, valid_to, source_uid, confirmed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    course_id=excluded.course_id,
                    weekday=excluded.weekday,
                    start_time=excluded.start_time,
                    end_time=excluded.end_time,
                    location=excluded.location,
                    valid_from=excluded.valid_from,
                    valid_to=excluded.valid_to,
                    source_uid=excluded.source_uid,
                    confirmed=excluded.confirmed
                """,
                (
                    session.id,
                    session.course_id,
                    session.weekday,
                    _time_text(session.start_time),
                    _time_text(session.end_time),
                    session.location,
                    _date_text(session.valid_from),
                    _date_text(session.valid_to),
                    session.source_uid,
                    int(session.confirmed),
                ),
            )
        return session

    def list_course_sessions(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM course_sessions ORDER BY weekday, start_time, id"
            ).fetchall()
        return [_course_session_from_row(row) for row in rows]

    def upsert_assignment(self, assignment):
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO assignments(
                    id, course_id, title, kind, weight, due_at, start_date,
                    status, estimated_minutes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(course_id, title, due_at) DO UPDATE SET
                    kind=excluded.kind,
                    weight=excluded.weight,
                    start_date=excluded.start_date,
                    status=excluded.status,
                    estimated_minutes=excluded.estimated_minutes,
                    updated_at=excluded.updated_at
                """,
                (
                    assignment.id,
                    assignment.course_id,
                    assignment.title,
                    assignment.kind,
                    assignment.weight,
                    _datetime_text(assignment.due_at),
                    _date_text(assignment.start_date),
                    assignment.status,
                    assignment.estimated_minutes,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM assignments WHERE course_id = ? AND title = ? "
                "AND due_at = ?",
                (
                    assignment.course_id,
                    assignment.title,
                    _datetime_text(assignment.due_at),
                ),
            ).fetchone()
        return _assignment_from_row(row)

    def get_assignment(self, assignment_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assignments WHERE id = ?",
                (assignment_id,),
            ).fetchone()
        return _assignment_from_row(row) if row else None

    def list_active_assignments(self, through=None):
        query = "SELECT * FROM assignments WHERE status != 'submitted'"
        parameters = []
        if through is not None:
            query += " AND start_date <= ?"
            parameters.append(_date_text(through.date() if hasattr(through, "date") else through))
        query += " ORDER BY due_at, id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_assignment_from_row(row) for row in rows]

    def upsert_math_plan_week(self, week):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO math_plan_weeks(
                    id, course_id, plan_key, week_number, start_date, end_date,
                    topic, target_minutes, done_criteria, hard_deadline,
                    status, compression_policy
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_key, week_number) DO UPDATE SET
                    course_id=excluded.course_id,
                    start_date=excluded.start_date,
                    end_date=excluded.end_date,
                    topic=excluded.topic,
                    target_minutes=excluded.target_minutes,
                    done_criteria=excluded.done_criteria,
                    hard_deadline=excluded.hard_deadline,
                    status=excluded.status,
                    compression_policy=excluded.compression_policy
                """,
                (
                    week.id,
                    week.course_id,
                    week.plan_key,
                    week.week_number,
                    _date_text(week.start_date),
                    _date_text(week.end_date),
                    week.topic,
                    week.target_minutes,
                    week.done_criteria,
                    _date_text(week.hard_deadline),
                    week.status,
                    week.compression_policy,
                ),
            )
        return week

    def list_math_plan_weeks(self, plan_key=None):
        query = "SELECT * FROM math_plan_weeks"
        parameters = []
        if plan_key is not None:
            query += " WHERE plan_key = ?"
            parameters.append(plan_key)
        query += " ORDER BY start_date, week_number"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_math_plan_week_from_row(row) for row in rows]

    def get_math_plan_week(self, plan_key, week_number):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM math_plan_weeks WHERE plan_key = ? AND week_number = ?",
                (plan_key, week_number),
            ).fetchone()
        return _math_plan_week_from_row(row) if row else None

    def add_progress_log(self, progress):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO progress_logs(
                    id, assignment_id, math_plan_week_id, percent, minutes, note, logged_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    progress.id,
                    progress.assignment_id,
                    progress.math_plan_week_id,
                    progress.percent,
                    progress.minutes,
                    progress.note,
                    _datetime_text(progress.logged_at),
                ),
            )
        return progress

    def latest_progress(self, assignment_id=None, math_plan_week_id=None):
        if (assignment_id is None) == (math_plan_week_id is None):
            raise ValueError("必须且只能指定 assignment_id 或 math_plan_week_id")
        if assignment_id is not None:
            field, value = "assignment_id", assignment_id
        else:
            field, value = "math_plan_week_id", math_plan_week_id
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM progress_logs WHERE " + field + " = ? "
                "ORDER BY logged_at DESC, id DESC LIMIT 1",
                (value,),
            ).fetchone()
        return _progress_log_from_row(row) if row else None

    @staticmethod
    def _write_study_block(connection, block):
        connection.execute(
            """
            INSERT INTO study_blocks(
                id, course_id, assignment_id, math_plan_week_id, block_date,
                start_time, end_time, title, block_type, status, priority,
                source, generation_key, note, compressed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                course_id=excluded.course_id,
                assignment_id=excluded.assignment_id,
                math_plan_week_id=excluded.math_plan_week_id,
                block_date=excluded.block_date,
                start_time=excluded.start_time,
                end_time=excluded.end_time,
                title=excluded.title,
                block_type=excluded.block_type,
                status=excluded.status,
                priority=excluded.priority,
                source=excluded.source,
                generation_key=excluded.generation_key,
                note=excluded.note,
                compressed=excluded.compressed
            """,
            (
                block.id,
                block.course_id,
                block.assignment_id,
                block.math_plan_week_id,
                _date_text(block.block_date),
                _time_text(block.start_time),
                _time_text(block.end_time),
                block.title,
                block.block_type,
                block.status,
                block.priority,
                block.source,
                block.generation_key,
                block.note,
                int(block.compressed),
                _now(),
            ),
        )

    def upsert_study_block(self, block):
        with self._connect() as connection:
            self._write_study_block(connection, block)
        return block

    def replace_generated_study_blocks(self, start_date, end_date, blocks):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM study_blocks WHERE source = 'generated' "
                "AND status = 'planned' AND block_date BETWEEN ? AND ?",
                (_date_text(start_date), _date_text(end_date)),
            )
            for block in blocks:
                self._write_study_block(connection, block)

    def list_study_blocks(self, start_date=None, end_date=None):
        query = "SELECT * FROM study_blocks"
        parameters = []
        conditions = []
        if start_date is not None:
            conditions.append("block_date >= ?")
            parameters.append(_date_text(start_date))
        if end_date is not None:
            conditions.append("block_date <= ?")
            parameters.append(_date_text(end_date))
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY block_date, start_time, id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_study_block_from_row(row) for row in rows]

    def upsert_deadline_reminder(self, reminder):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO deadline_reminders(
                    id, assignment_id, remind_at, reminder_type, target_percent,
                    message, status, sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(assignment_id, reminder_type, remind_at) DO UPDATE SET
                    target_percent=excluded.target_percent,
                    message=excluded.message,
                    status=excluded.status,
                    sent_at=excluded.sent_at
                """,
                (
                    reminder.id,
                    reminder.assignment_id,
                    _datetime_text(reminder.remind_at),
                    reminder.reminder_type,
                    reminder.target_percent,
                    reminder.message,
                    reminder.status,
                    _datetime_text(reminder.sent_at),
                ),
            )
        return reminder

    def list_deadline_reminders(self, assignment_id=None):
        query = "SELECT * FROM deadline_reminders"
        parameters = []
        if assignment_id is not None:
            query += " WHERE assignment_id = ?"
            parameters.append(assignment_id)
        query += " ORDER BY remind_at, id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_deadline_reminder_from_row(row) for row in rows]

    def get_policy(self, event_type):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT lead_minutes, quiet_start, quiet_end, enabled "
                "FROM reminder_policy WHERE event_type = ?",
                (event_type,),
            ).fetchone()
        return dict(row) if row else None

    def export_data(self):
        tables = (
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
        )
        exported = {}
        with self._connect() as connection:
            for table in tables:
                rows = connection.execute("SELECT * FROM " + table).fetchall()
                exported[table] = [dict(row) for row in rows]
        return exported
