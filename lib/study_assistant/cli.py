import argparse
import contextlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from dataclasses import asdict
from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .diagnostics import (
    run_diagnostics,
    verify_model,
    verify_vision,
    write_red_vision_fixture,
)
from .hermes import CommandResult, HermesRunner
from .i18n import ChineseArgumentParser
from .models import (
    Assignment,
    Course,
    DeadlineReminder,
    DeliveryTarget,
    ProgressLog,
    StudentProfile,
)
from .paths import RuntimePaths
from .repository import Repository
from .seed_data import MATH_PLAN_KEY, seed_demo, seed_math_plan
from .study_planner import StudyPlanner


class UsageError(ValueError):
    pass


def _timezone(value):
    if value == "UTC":
        return value
    component = r"[A-Za-z0-9](?:[A-Za-z0-9._+-]*[A-Za-z0-9])?"
    if not re.fullmatch(component + r"(?:/" + component + r")+", value):
        raise argparse.ArgumentTypeError("时区必须使用类似 IANA 的 Area/Location 格式")
    return value


def _clock_time(value):
    match = re.fullmatch(r"(\d{2}):(\d{2})", value)
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        raise argparse.ArgumentTypeError("时间必须使用 24 小时制 HH:MM 格式")
    return value


def _nonnegative_integer(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("数值必须是非负整数") from error
    if number < 0:
        raise argparse.ArgumentTypeError("数值必须是非负整数")
    return number


def _positive_integer(value):
    number = _nonnegative_integer(value)
    if number == 0:
        raise argparse.ArgumentTypeError("数值必须是正整数")
    return number


def _percentage(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("进度必须是 0 到 100 的整数") from error
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError("进度必须是 0 到 100 的整数")
    return number


def _weight(value):
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("权重必须是 0 到 100 的数字") from error
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError("权重必须是 0 到 100 的数字")
    return number


def _date_value(value):
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("日期必须使用 YYYY-MM-DD 格式") from error


def _due_value(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "截止时间必须使用 YYYY-MM-DD HH:MM 格式"
        ) from error


def _iso_week(value):
    match = re.fullmatch(r"(\d{4})-W(\d{2})", value)
    if not match:
        raise argparse.ArgumentTypeError("周必须使用 YYYY-Www 格式，例如 2037-W32")
    try:
        return date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("ISO 周不存在") from error


def _json_default(value):
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    raise TypeError("无法序列化 {}".format(type(value).__name__))


def _build_parser():
    parser = ChineseArgumentParser(
        prog="24h_assistant.py",
        description="24h 留学助理阶段 0/1 本地管理工具",
    )
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        title="命令（实际输入保持英文）",
    )

    commands.add_parser("init", help="初始化本地产品数据库")

    profile = commands.add_parser("profile", help="设置或查看学生画像")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    profile_set = profile_commands.add_parser("set")
    profile_set.add_argument("--school", required=True)
    profile_set.add_argument("--campus", required=True)
    profile_set.add_argument("--city", required=True)
    profile_set.add_argument("--timezone", required=True, type=_timezone)
    profile_set.add_argument("--language", default="zh-CN")
    profile_set.add_argument("--degree")
    profile_set.add_argument("--major")
    profile_show = profile_commands.add_parser("show")
    profile_show.add_argument("--json", action="store_true")

    consent = commands.add_parser("consent", help="管理独立同意项")
    consent_commands = consent.add_subparsers(dest="consent_command", required=True)
    consent_set = consent_commands.add_parser("set")
    consent_set.add_argument("module")
    consent_set.add_argument("state", choices=("granted", "revoked"))
    consent_set.add_argument("--policy-version", required=True)

    delivery = commands.add_parser("delivery", help="管理并测试主消息投递目标")
    delivery_commands = delivery.add_subparsers(dest="delivery_command", required=True)
    delivery_set = delivery_commands.add_parser("set")
    delivery_set.add_argument("--platform", required=True)
    delivery_set.add_argument("--target", required=True)
    delivery_commands.add_parser("test")

    policy = commands.add_parser("policy", help="管理提醒策略")
    policy_commands = policy.add_subparsers(dest="policy_command", required=True)
    policy_set = policy_commands.add_parser("set")
    policy_set.add_argument("event_type")
    policy_set.add_argument("--lead-minutes", required=True, type=_nonnegative_integer)
    policy_set.add_argument("--quiet-start", required=True, type=_clock_time)
    policy_set.add_argument("--quiet-end", required=True, type=_clock_time)

    feedback = commands.add_parser("feedback", help="记录提醒反馈")
    feedback_commands = feedback.add_subparsers(dest="feedback_command", required=True)
    feedback_record = feedback_commands.add_parser("record")
    feedback_record.add_argument("reminder_id")
    feedback_record.add_argument("action", choices=("complete", "later", "useless"))

    data = commands.add_parser("data", help="导出或清除产品数据")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    data_export = data_commands.add_parser("export")
    data_export.add_argument("--output", required=True)
    data_clear = data_commands.add_parser("clear")
    data_clear.add_argument("--confirm", required=True)

    doctor = commands.add_parser("doctor", help="运行不消耗模型额度的就绪诊断")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--api-base-url")

    verify = commands.add_parser("verify", help="显式验证模型或 Vision 能力")
    verify_commands = verify.add_subparsers(dest="verify_command", required=True)
    verify_commands.add_parser("model")
    verify_commands.add_parser("vision")

    cron = commands.add_parser("cron", help="创建受管 Cron 冒烟测试任务")
    cron.add_subparsers(dest="cron_command", required=True).add_parser("smoke-create")

    assignment = commands.add_parser("assignment", help="管理结构化作业")
    assignment_commands = assignment.add_subparsers(
        dest="assignment_command",
        required=True,
    )
    assignment_add = assignment_commands.add_parser("add", help="添加作业")
    assignment_add.add_argument("--course", required=True)
    assignment_add.add_argument("--title", required=True)
    assignment_add.add_argument("--weight", required=True, type=_weight)
    assignment_add.add_argument("--due", required=True, type=_due_value)
    assignment_add.add_argument("--start-date", type=_date_value)
    assignment_add.add_argument("--kind", default="assignment")
    assignment_add.add_argument(
        "--estimated-minutes",
        type=_positive_integer,
        default=600,
    )

    plan = commands.add_parser("plan", help="生成或查看结构化学习计划")
    plan_commands = plan.add_subparsers(dest="plan_command", required=True)
    plan_generate = plan_commands.add_parser("generate", help="生成指定 ISO 周计划")
    plan_generate.add_argument("--week", required=True, type=_iso_week)
    plan_show = plan_commands.add_parser("show", help="查看已保存计划")
    plan_show.add_argument("--week", type=_iso_week)
    plan_show.add_argument("--json", action="store_true")

    progress = commands.add_parser("progress", help="记录作业完成进度")
    progress_commands = progress.add_subparsers(dest="progress_command", required=True)
    progress_log = progress_commands.add_parser("log", help="追加作业进度日志")
    progress_log.add_argument("--assignment-id", required=True)
    progress_log.add_argument("--percent", required=True, type=_percentage)
    progress_log.add_argument("--note")

    math_plan = commands.add_parser("math-plan", help="管理七周数学基础计划")
    math_plan_commands = math_plan.add_subparsers(
        dest="math_plan_command",
        required=True,
    )
    math_plan_commands.add_parser("init", help="初始化七周数学计划")
    math_log = math_plan_commands.add_parser("log", help="记录数学周进度")
    math_log.add_argument("--week", required=True, type=_positive_integer)
    math_log.add_argument("--percent", required=True, type=_percentage)
    math_log.add_argument("--minutes", type=_nonnegative_integer, default=0)
    math_log.add_argument("--note")

    seed = commands.add_parser("seed", help="导入已确认的结构化学业数据")
    seed.add_subparsers(dest="seed_command", required=True).add_parser(
        "demo",
        help="导入虚构课程、数学计划、示例作业和课表锚点",
    )
    return parser


def _require_database(paths):
    if not paths.database.is_file():
        raise RuntimeError("产品数据库尚未初始化；请先运行 `init`。")
    return Repository(paths.database)


def _print_profile(profile, as_json, stdout):
    if as_json:
        print(json.dumps(asdict(profile), ensure_ascii=False, sort_keys=True), file=stdout)
        return
    labels = {
        "school": "学校",
        "campus": "校区",
        "city": "城市",
        "timezone": "时区",
        "language": "语言",
        "degree": "学位项目",
        "major": "专业",
    }
    for key, value in asdict(profile).items():
        if value is not None:
            print("{}：{}".format(labels[key], value), file=stdout)


def _require_profile(repository):
    profile = repository.get_profile()
    if profile is None:
        raise RuntimeError("尚未设置学生画像；请先运行 `profile set`。")
    return profile


def _term_for_date(value):
    semester = "S1" if value.month <= 6 else "S2"
    return "{}-{}".format(value.year, semester)


def _stable_id(prefix, value):
    return prefix + "-" + uuid5(NAMESPACE_URL, value).hex


def _ensure_course(repository, code, due_at, timezone_name):
    existing = repository.get_course_by_code(code)
    if existing:
        return existing
    term = _term_for_date(due_at.date())
    return repository.upsert_course(
        Course(
            _stable_id("course", "{}:{}".format(code, term)),
            code,
            code,
            term,
            timezone_name,
        )
    )


def _save_assignment_reminders(repository, assignment, planner):
    for milestone in planner.milestones_for_assignment(assignment):
        if milestone.target_percent == 100:
            remind_at = assignment.due_at
        else:
            remind_at = datetime.combine(
                milestone.on_date,
                time(9, 0),
                planner.timezone,
            )
        key = "{}:{}:{}".format(
            assignment.id,
            milestone.target_percent,
            remind_at.isoformat(),
        )
        repository.upsert_deadline_reminder(
            DeadlineReminder(
                _stable_id("reminder", key),
                assignment.id,
                remind_at,
                "milestone-{}".format(milestone.target_percent),
                milestone.action,
                target_percent=milestone.target_percent,
            )
        )


def _week_label(week_start):
    iso = week_start.isocalendar()
    return "{}-W{:02d}".format(iso.year, iso.week)


def _plan_payload(blocks):
    return {
        "compressed": any(block.compressed for block in blocks),
        "blocks": [asdict(block) for block in blocks],
    }


def _remove_product_data(repository, runner):
    for job in repository.list_managed_cron_jobs():
        result = runner.run("cron", "delete", job["job_id"])
        if result.returncode != 0:
            raise RuntimeError("无法删除受管 Cron 任务；已保留产品数据。")
        repository.delete_managed_cron_job(job["job_id"])

    database = repository.database
    for path in (Path(str(database) + "-wal"), Path(str(database) + "-shm"), database):
        path.unlink(missing_ok=True)


def _render_report(report, as_json, stdout):
    if as_json:
        print(report.to_json(), file=stdout)
        return
    status_labels = {"pass": "通过", "warn": "警告", "fail": "失败"}
    check_labels = {
        "hermes_version": "Hermes 版本",
        "config": "Hermes 配置",
        "gateway": "Gateway",
        "cron": "Cron 调度器",
        "model": "模型路由",
        "database": "产品数据库",
        "delivery": "消息投递",
        "api_health": "API Server 健康状态",
        "api_auth": "API Server 认证边界",
    }
    for name, check in report.checks.items():
        print(
            "【{}】 {}：{}".format(
                status_labels.get(check.status, check.status),
                check_labels.get(name, name),
                check.summary,
            ),
            file=stdout,
        )
        if check.detail:
            print("  {}".format(check.detail), file=stdout)
        if check.remediation:
            print("  修复建议：{}".format(check.remediation), file=stdout)


def _primary_delivery(repository):
    delivery = repository.get_primary_delivery()
    if delivery is None:
        raise RuntimeError("尚未配置主消息投递目标。")
    return delivery


def _create_smoke_cron(repository, runner):
    if any(job["purpose"] == "smoke" for job in repository.list_managed_cron_jobs()):
        raise RuntimeError("受管的 Cron 冒烟测试任务已存在。")

    delivery = _primary_delivery(repository)
    result = runner.run(
        "cron",
        "create",
        "1m",
        "--name",
        "24h-assistant-smoke",
        "--deliver",
        delivery.target,
        "--script",
        "24h_smoke_reminder.py",
        "--no-agent",
    )
    if result.returncode != 0:
        raise RuntimeError("Cron 冒烟测试任务创建失败。")
    match = re.search(r"(?m)^Created job:\s*([A-Za-z0-9_-]{1,128})\s*$", result.stdout)
    if not match:
        raise RuntimeError(
            "Hermes 已创建 Cron 任务，但无法记录任务 ID；"
            "重试前请检查 `hermes cron list`。"
        )
    job_id = match.group(1)
    try:
        repository.register_cron_job(job_id, "smoke")
    except (OSError, sqlite3.Error):
        runner.run("cron", "delete", job_id)
        raise
    return job_id


def _dispatch(args, paths, stdout, runner, opener):
    if args.command == "init":
        Repository(paths.database).initialize()
        print("已初始化产品数据库：{}".format(paths.database), file=stdout)
        return 0

    if args.command == "profile" and args.profile_command == "set":
        repository = Repository(paths.database)
        repository.initialize()
        repository.save_profile(
            StudentProfile(
                school=args.school,
                campus=args.campus,
                city=args.city,
                timezone=args.timezone,
                language=args.language,
                degree=args.degree,
                major=args.major,
            )
        )
        print("已保存学生画像", file=stdout)
        return 0

    if args.command == "profile" and args.profile_command == "show":
        profile = _require_database(paths).get_profile()
        if profile is None:
            raise RuntimeError("尚未设置学生画像。")
        _print_profile(profile, args.json, stdout)
        return 0

    if args.command == "consent":
        repository = Repository(paths.database)
        repository.initialize()
        repository.set_consent(
            args.module,
            args.state == "granted",
            args.policy_version,
        )
        print("已保存同意项状态", file=stdout)
        return 0

    if args.command == "delivery" and args.delivery_command == "set":
        repository = Repository(paths.database)
        repository.initialize()
        repository.set_primary_delivery(DeliveryTarget(args.platform, args.target))
        print("已保存主消息投递目标", file=stdout)
        return 0

    if args.command == "delivery" and args.delivery_command == "test":
        repository = _require_database(paths)
        delivery = _primary_delivery(repository)
        result = runner.run(
            "send",
            "--to",
            delivery.target,
            "24h 留学助理测试消息：消息平台连接成功。",
        )
        if result.returncode != 0:
            raise RuntimeError("测试消息投递失败。")
        print("测试消息已投递", file=stdout)
        return 0

    if args.command == "policy":
        repository = Repository(paths.database)
        repository.initialize()
        repository.set_policy(
            args.event_type,
            args.lead_minutes,
            args.quiet_start,
            args.quiet_end,
        )
        print("已保存提醒策略", file=stdout)
        return 0

    if args.command == "feedback":
        repository = Repository(paths.database)
        repository.initialize()
        repository.record_feedback(args.reminder_id, args.action)
        print("已保存提醒反馈", file=stdout)
        return 0

    if args.command == "data" and args.data_command == "export":
        repository = _require_database(paths)
        output = Path(args.output).expanduser()
        if output.resolve() == paths.database.resolve():
            raise UsageError("导出文件不能覆盖产品数据库。")
        output.write_text(
            json.dumps(repository.export_data(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            output.chmod(0o600)
        print("已导出产品数据至：{}".format(output), file=stdout)
        return 0

    if args.command == "data" and args.data_command == "clear":
        if args.confirm != "CLEAR-24H-DATA":
            raise UsageError("确认文本必须严格为 CLEAR-24H-DATA。")
        repository = _require_database(paths)
        _remove_product_data(repository, runner)
        print("已清除产品数据和受管 Cron 任务", file=stdout)
        return 0

    if args.command == "doctor":
        primary_target = None
        if paths.database.is_file():
            primary = Repository(paths.database).get_primary_delivery()
            primary_target = primary.target if primary else None
        kwargs = {}
        if opener is not None:
            kwargs["opener"] = opener
        report = run_diagnostics(
            runner,
            primary_target=primary_target,
            database=paths.database,
            hermes_home=paths.hermes_home,
            api_base_url=args.api_base_url,
            **kwargs
        )
        _render_report(report, args.json, stdout)
        return 0 if report.ok else 1

    if args.command == "verify" and args.verify_command == "model":
        result = verify_model(runner)
        if result.returncode != 0 or result.stdout.strip() != "MODEL_OK":
            raise RuntimeError("模型验证失败。")
        print("模型验证通过（MODEL_OK）", file=stdout)
        return 0

    if args.command == "verify" and args.verify_command == "vision":
        descriptor, raw_path = tempfile.mkstemp(prefix="24h-vision-", suffix=".png")
        os.close(descriptor)
        fixture = Path(raw_path)
        try:
            write_red_vision_fixture(fixture)
            result = verify_vision(runner, fixture)
            if result.returncode != 0 or result.stdout.strip() != "VISION_OK":
                raise RuntimeError("Vision 图像验证失败。")
            print("Vision 图像验证通过（VISION_OK）", file=stdout)
            return 0
        finally:
            fixture.unlink(missing_ok=True)

    if args.command == "cron" and args.cron_command == "smoke-create":
        repository = Repository(paths.database)
        repository.initialize()
        job_id = _create_smoke_cron(repository, runner)
        print("已创建受管 Cron 冒烟测试任务：{}".format(job_id), file=stdout)
        return 0

    if args.command == "assignment" and args.assignment_command == "add":
        repository = Repository(paths.database)
        repository.initialize()
        profile = _require_profile(repository)
        timezone_info = ZoneInfo(profile.timezone)
        due_at = args.due.replace(tzinfo=timezone_info)
        course = _ensure_course(repository, args.course, due_at, profile.timezone)
        provisional_start = args.start_date or due_at.date()
        provisional = Assignment(
            "assignment-" + uuid4().hex,
            course.id,
            args.title,
            args.kind,
            args.weight,
            due_at,
            provisional_start,
            estimated_minutes=args.estimated_minutes,
        )
        planner = StudyPlanner(profile.timezone)
        start_date = args.start_date or planner.milestones_for_assignment(provisional)[0].on_date
        if start_date > due_at.date():
            raise UsageError("作业开工日期不能晚于截止日期。")
        assignment = Assignment(
            provisional.id,
            provisional.course_id,
            provisional.title,
            provisional.kind,
            provisional.weight,
            provisional.due_at,
            start_date,
            provisional.status,
            provisional.estimated_minutes,
        )
        assignment = repository.upsert_assignment(assignment)
        _save_assignment_reminders(repository, assignment, planner)
        print(
            "已添加作业：{} · {}（ID：{}）".format(
                course.code,
                assignment.title,
                assignment.id,
            ),
            file=stdout,
        )
        return 0

    if args.command == "plan" and args.plan_command == "generate":
        repository = _require_database(paths)
        profile = _require_profile(repository)
        policy = repository.get_policy("study")
        quiet_start = time(22, 30)
        quiet_end = time(7, 0)
        if policy and policy["enabled"]:
            quiet_start = datetime.strptime(policy["quiet_start"], "%H:%M").time()
            quiet_end = datetime.strptime(policy["quiet_end"], "%H:%M").time()
        planner = StudyPlanner(profile.timezone, quiet_start, quiet_end)
        week_start = args.week
        week_end = week_start + timedelta(days=6)
        assignments = repository.list_active_assignments(through=week_end)
        progress = {}
        for assignment in assignments:
            latest = repository.latest_progress(assignment_id=assignment.id)
            progress[assignment.id] = latest.percent if latest else 0
        generated = planner.generate_week(
            week_start,
            assignments,
            repository.list_course_sessions(),
            progress,
        )
        repository.replace_generated_study_blocks(
            generated.week_start,
            generated.week_end,
            generated.blocks,
        )
        suffix = "；检测到落后，已压缩剩余计划" if generated.compressed else ""
        print(
            "已生成 {} 学习计划：{} 个时间块{}".format(
                _week_label(week_start),
                len(generated.blocks),
                suffix,
            ),
            file=stdout,
        )
        return 0

    if args.command == "plan" and args.plan_command == "show":
        repository = _require_database(paths)
        if args.week:
            start_date = args.week
            end_date = start_date + timedelta(days=6)
        else:
            start_date = end_date = None
        blocks = repository.list_study_blocks(start_date, end_date)
        payload = _plan_payload(blocks)
        if args.json:
            print(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=_json_default,
                ),
                file=stdout,
            )
            return 0
        if not blocks:
            print("当前没有已保存的学习时间块", file=stdout)
            return 0
        for block in blocks:
            marker = "【压缩】" if block.compressed else ""
            print(
                "{} {}-{} {}{}".format(
                    block.block_date.isoformat(),
                    block.start_time.isoformat(timespec="minutes"),
                    block.end_time.isoformat(timespec="minutes"),
                    marker,
                    block.title,
                ),
                file=stdout,
            )
        return 0

    if args.command == "progress" and args.progress_command == "log":
        repository = _require_database(paths)
        assignment = repository.get_assignment(args.assignment_id)
        if assignment is None:
            raise UsageError("找不到指定的作业 ID。")
        progress = ProgressLog(
            "progress-" + uuid4().hex,
            args.percent,
            0,
            datetime.now(timezone.utc),
            assignment_id=assignment.id,
            note=args.note,
        )
        repository.add_progress_log(progress)
        print(
            "已记录作业进度：{}%{}".format(
                progress.percent,
                " · " + progress.note if progress.note else "",
            ),
            file=stdout,
        )
        return 0

    if args.command == "math-plan" and args.math_plan_command == "init":
        repository = Repository(paths.database)
        stats = seed_math_plan(repository)
        print(
            "已初始化 DEMO1001 七周数学计划：{} 周，{} 个时间块".format(
                stats["math_weeks"],
                stats["math_blocks"],
            ),
            file=stdout,
        )
        return 0

    if args.command == "math-plan" and args.math_plan_command == "log":
        repository = _require_database(paths)
        week = repository.get_math_plan_week(MATH_PLAN_KEY, args.week)
        if week is None:
            raise UsageError("找不到指定数学周；请先运行 `math-plan init`。")
        progress = ProgressLog(
            "progress-" + uuid4().hex,
            args.percent,
            args.minutes,
            datetime.now(timezone.utc),
            math_plan_week_id=week.id,
            note=args.note,
        )
        repository.add_progress_log(progress)
        print(
            "已记录数学计划第 {} 周进度：{}%，{} 分钟{}".format(
                week.week_number,
                progress.percent,
                progress.minutes,
                " · " + progress.note if progress.note else "",
            ),
            file=stdout,
        )
        return 0

    if args.command == "seed" and args.seed_command == "demo":
        repository = Repository(paths.database)
        stats = seed_demo(repository)
        print(
            "已导入 DEMO1001 公开示例数据：{} 门课程、{} 周数学计划、"
            "{} 个数学时间块、{} 个 A1 里程碑".format(
                stats["courses"],
                stats["math_weeks"],
                stats["math_blocks"],
                stats["milestones"],
            ),
            file=stdout,
        )
        return 0

    raise RuntimeError("不支持该命令。")


def main(argv=None, stdout=None, stderr=None, runner=None, opener=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = _build_parser()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            args = parser.parse_args(argv)
        except SystemExit as error:
            return int(error.code)

    try:
        paths = RuntimePaths.from_environment()
        return _dispatch(
            args,
            paths,
            stdout,
            runner or HermesRunner(),
            opener,
        )
    except UsageError as error:
        print(str(error), file=stderr)
        return 2
    except (OSError, RuntimeError, sqlite3.Error, ValueError, ZoneInfoNotFoundError) as error:
        print(str(error), file=stderr)
        return 1
