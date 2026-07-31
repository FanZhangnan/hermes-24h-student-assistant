from datetime import date, datetime, time
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from .models import (
    Assignment,
    Course,
    CourseSession,
    DeadlineReminder,
    MathPlanWeek,
    StudyBlock,
)


TIMEZONE = "UTC"
TERM = "DEMO-TERM"
TERM_START = date(2037, 7, 27)
TERM_END = date(2037, 10, 30)
MATH_PLAN_KEY = "demo-math-plan"
MATH_HARD_DEADLINE = date(2037, 9, 16)
COMPRESSION_POLICY = (
    "落后时合并相邻主题并砍掉低杠杆练习；保留定义和模板题，"
    "禁止整体顺延过 2037-09-16。"
)


COURSES = (
    (
        "DEMO1001",
        "示例机器学习",
        "https://example.invalid/courses/DEMO1001",
    ),
    ("DEMO2001", "示例毕业项目", None),
    ("DEMO3001", "示例数据挖掘", None),
    ("DEMO4001", "示例商业分析", None),
)


COURSE_SESSIONS = (
    ("DEMO2001", 0, "08:00", "11:00", "项目研讨课"),
    ("DEMO3001", 0, "12:00", "14:00", "数据挖掘讲座"),
    ("DEMO1001", 1, "10:00", "12:00", "机器学习讲座"),
    ("DEMO1001", 2, "12:00", "13:00", "机器学习实践课"),
    ("DEMO4001", 2, "18:00", "19:00", "商业分析研讨课"),
    ("DEMO1001", 3, "11:00", "12:00", "机器学习实验课"),
    ("DEMO3001", 4, "10:00", "12:00", "数据挖掘实践课"),
)


MATH_WEEKS = (
    {
        "week": 1,
        "start": "2037-07-30",
        "end": "2037-08-05",
        "topic": "符号识字",
        "minutes": 180,
        "done": "看到讲义公式能念出符号含义；不要求会算",
        "sessions": (
            (
                "2037-07-30",
                "13:00",
                "14:30",
                "符号表上半：常见数学符号与下标；手写 1 页速查",
            ),
            (
                "2037-08-01",
                "10:00",
                "11:30",
                "符号表下半：期望、方差、梯度和偏导只识读不计算",
            ),
        ),
    },
    {
        "week": 2,
        "start": "2037-08-06",
        "end": "2037-08-12",
        "topic": "直线方程与共线判断",
        "minutes": 180,
        "done": "共线和直线题 8/10 稳定正确",
        "sessions": (
            ("2037-08-06", "13:00", "14:30", "两点式、点斜式与三点共线判断"),
            (
                "2037-08-11",
                "19:30",
                "21:00",
                "10 道迷你题限时；错题只订正模板不扩展",
            ),
        ),
    },
    {
        "week": 3,
        "start": "2037-08-13",
        "end": "2037-08-19",
        "topic": "向量（点积、长度）",
        "minutes": 240,
        "done": "能手算 2D/3D 点积与长度，并解释点积大代表更同向",
        "sessions": (
            (
                "2037-08-13",
                "13:00",
                "15:00",
                "向量加减、标量乘、范数、单位向量和点积几何意义",
            ),
            ("2037-08-14", "13:00", "14:00", "余弦相似度手算 2 至 3 题"),
            ("2037-08-18", "19:30", "20:30", "混合小测 15 分钟并订正"),
        ),
    },
    {
        "week": 4,
        "start": "2037-08-20",
        "end": "2037-08-26",
        "topic": "矩阵（维度、转置、乘法规则）",
        "minutes": 240,
        "done": "能判断矩阵能否相乘及结果维度，2x2 乘法正确",
        "sessions": (
            (
                "2037-08-20",
                "19:30",
                "20:00",
                "可选预习：矩阵维度读写；如与 A1 冲突则取消",
            ),
            ("2037-08-21", "16:00", "17:30", "A1 提交后学习转置和矩阵乘法规则"),
            (
                "2037-08-25",
                "13:00",
                "15:00",
                "矩阵乘法练习、维度判断并连接讲义中的 Xw",
            ),
        ),
    },
    {
        "week": 5,
        "start": "2037-08-27",
        "end": "2037-09-02",
        "topic": "协方差矩阵与特征值（概念层）",
        "minutes": 240,
        "done": "能解释 PCA 三步和协方差矩阵各元素含义；不手算特征值",
        "sessions": (
            (
                "2037-08-27",
                "13:00",
                "15:00",
                "方差、协方差、对称矩阵和中心化的概念",
            ),
            (
                "2037-09-01",
                "13:00",
                "15:00",
                "PCA、特征值向量概念、碎石图和投影示意图",
            ),
        ),
    },
    {
        "week": 6,
        "start": "2037-09-03",
        "end": "2037-09-09",
        "topic": "函数记号、卷积与池化手算",
        "minutes": 240,
        "done": "限时完成卷积和池化填数，不依赖程序",
        "sessions": (
            ("2037-09-03", "13:00", "15:00", "函数记号扫盲和二维卷积小核手算"),
            (
                "2037-09-08",
                "13:00",
                "15:00",
                "max/avg pooling 与卷积到激活再到池化完整题",
            ),
        ),
    },
    {
        "week": 7,
        "start": "2037-09-10",
        "end": "2037-09-16",
        "topic": "真题全真演练与补漏",
        "minutes": 240,
        "done": "放弃高难推导后，模拟卷稳定达到 50 分策略路径",
        "sessions": (
            ("2037-09-10", "13:00", "15:00", "一套往年卷：只做已覆盖题型和选择题"),
            (
                "2037-09-15",
                "13:00",
                "15:00",
                "另一套卷对应章节并整理不超过 5 个失分点",
            ),
        ),
    },
)


A1_MILESTONES = (
    ("2037-07-30", 0, "开工：读懂要求和评分标准，列出任务拆解"),
    ("2037-08-04", 25, "完成资料收集、数据探索和框架搭建"),
    ("2037-08-09", 50, "完成主体分析或核心实现"),
    ("2037-08-14", 75, "完成初稿主体，确保文字或代码主路径可运行"),
    ("2037-08-19", 90, "完整初稿冻结，进入检查、润色和测试"),
    ("2037-08-21", 100, "提交前最终检查：格式、引用、AI 声明和上传"),
)


def _stable_id(prefix, value):
    return prefix + "-" + uuid5(NAMESPACE_URL, value).hex


def _date(value):
    return date.fromisoformat(value)


def _time(value):
    return time.fromisoformat(value)


def _ensure_courses(repository):
    courses = {}
    for code, title, profile_url in COURSES:
        course = repository.upsert_course(
            Course(
                _stable_id("course", "{}:{}".format(code, TERM)),
                code,
                title,
                TERM,
                TIMEZONE,
                profile_url,
            )
        )
        courses[code] = course
    return courses


def seed_math_plan(repository):
    repository.initialize()
    courses = _ensure_courses(repository)
    course = courses["DEMO1001"]
    for definition in MATH_WEEKS:
        week = MathPlanWeek(
            _stable_id("math-week", "{}:{}".format(MATH_PLAN_KEY, definition["week"])),
            course.id,
            MATH_PLAN_KEY,
            definition["week"],
            _date(definition["start"]),
            _date(definition["end"]),
            definition["topic"],
            definition["minutes"],
            definition["done"],
            MATH_HARD_DEADLINE,
            COMPRESSION_POLICY,
        )
        repository.upsert_math_plan_week(week)
        for session_date, start, end, task in definition["sessions"]:
            key = "{}:{}:{}".format(week.id, session_date, start)
            repository.upsert_study_block(
                StudyBlock(
                    _stable_id("block", key),
                    _date(session_date),
                    _time(start),
                    _time(end),
                    "DEMO1001 数学 W{} · {}".format(
                        definition["week"],
                        definition["topic"],
                    ),
                    "math",
                    "planned",
                    75,
                    "seed",
                    course_id=course.id,
                    math_plan_week_id=week.id,
                    generation_key="seed:" + key,
                    note=task + "；完成标准：" + definition["done"],
                )
            )
    return {"math_weeks": len(MATH_WEEKS), "math_blocks": 16}


def seed_demo(repository):
    repository.initialize()
    courses = _ensure_courses(repository)
    for code, weekday, start, end, label in COURSE_SESSIONS:
        key = "{}:{}:{}:{}".format(TERM, code, weekday, start)
        repository.upsert_course_session(
            CourseSession(
                _stable_id("session", key),
                courses[code].id,
                weekday,
                _time(start),
                _time(end),
                label,
                TERM_START,
                TERM_END,
                "seed:" + key,
            )
        )

    timezone = ZoneInfo(TIMEZONE)
    a1 = repository.upsert_assignment(
        Assignment(
            _stable_id("assignment", "DEMO1001:2037-S2:A1"),
            courses["DEMO1001"].id,
            "Assignment 1",
            "assignment",
            15,
            datetime(2037, 8, 21, 15, 0, tzinfo=timezone),
            date(2037, 7, 30),
        )
    )
    for milestone_date, target, message in A1_MILESTONES:
        if target == 100:
            remind_at = a1.due_at
        else:
            remind_at = datetime.combine(_date(milestone_date), time(9, 0), timezone)
        key = "{}:{}:{}".format(a1.id, target, remind_at.isoformat())
        repository.upsert_deadline_reminder(
            DeadlineReminder(
                _stable_id("reminder", key),
                a1.id,
                remind_at,
                "milestone-{}".format(target),
                message,
                target_percent=target,
            )
        )

    math_stats = seed_math_plan(repository)
    return {
        "courses": len(COURSES),
        "course_sessions": len(COURSE_SESSIONS),
        "assignments": 1,
        "milestones": len(A1_MILESTONES),
        **math_stats,
    }
