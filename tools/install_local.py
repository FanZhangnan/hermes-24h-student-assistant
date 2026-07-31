#!/usr/bin/env python3
import argparse
import contextlib
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.study_assistant.hermes import CommandResult
from lib.study_assistant.i18n import ChineseArgumentParser


class SubprocessRunner:
    def run(self, *args):
        try:
            completed = subprocess.run(
                list(args),
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(124, "", "命令执行超时")
        except OSError:
            return CommandResult(127, "", "无法启动命令")
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _parser():
    parser = ChineseArgumentParser(
        description="将本地 24h 留学助理扩展包安装到 Hermes Profile。"
    )
    parser.add_argument(
        "--profile",
        default="24h-assistant",
        help="目标 Profile 名称（默认：24h-assistant）",
    )
    parser.add_argument(
        "--clone-from",
        default="default",
        help="首次安装时要克隆的源 Profile（默认：default）",
    )
    parser.add_argument(
        "--source",
        default=str(ROOT),
        help="本地扩展包 Git 工作树路径",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="允许覆盖本命令执行前已存在的 Profile",
    )
    parser.add_argument(
        "--api-port",
        type=_port,
        help="设置本机回环 API Server 端口（新 Profile 默认为 8643）",
    )
    return parser


def _valid_profile_name(value):
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*", value))


def _port(value):
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("API 端口必须是整数") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("API 端口必须介于 1 和 65535 之间")
    return port


def _supported_version(output):
    match = re.search(r"\bv?(\d+)\.(\d+)\.(\d+)\b", output)
    return bool(match and tuple(int(part) for part in match.groups()) >= (0, 19, 0))


def _profile_exists(output, profile):
    pattern = r"(?m)^[ \t◆*]*{}(?:[ \t]|$)".format(re.escape(profile))
    return bool(re.search(pattern, output))


def _run_required(runner, command, failure_message):
    result = runner.run(*command)
    if result.returncode != 0:
        raise RuntimeError(failure_message)
    return result


def install_profile(profile, clone_from, source, force, runner, api_port=None):
    version = _run_required(
        runner,
        ("hermes", "--version"),
        "无法启动 Hermes Agent。",
    )
    if not _supported_version(version.stdout):
        raise RuntimeError("需要 Hermes Agent 0.19.0 或更高版本。")

    profiles = _run_required(
        runner,
        ("hermes", "profile", "list"),
        "无法列出 Hermes Profile。",
    )
    existed = _profile_exists(profiles.stdout, profile)
    if existed and not force:
        raise ValueError(
            "Profile `{}` 已存在；请检查后使用 --force 重新运行。".format(profile)
        )

    if not existed:
        _run_required(
            runner,
            ("hermes", "profile", "create", profile, "--clone-from", clone_from),
            "Hermes Profile 创建失败。",
        )

    git_source = source / ".git"
    _run_required(
        runner,
        (
            "hermes",
            "profile",
            "install",
            str(git_source),
            "--name",
            profile,
            "--force",
            "--yes",
        ),
        "Hermes 扩展包安装失败。",
    )
    selected_port = api_port if api_port is not None else (8643 if not existed else None)
    if selected_port is not None:
        _run_required(
            runner,
            (
                profile,
                "config",
                "set",
                "platforms.api_server.extra.port",
                str(selected_port),
            ),
            "无法配置当前 Profile 的 API Server 端口。",
        )
    _run_required(
        runner,
        (profile, "doctor"),
        "已安装的 Profile 未通过 Hermes doctor 检查。",
    )


def main(argv=None, stdout=None, stderr=None, runner=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = _parser()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            args = parser.parse_args(argv)
        except SystemExit as error:
            return int(error.code)

    if not _valid_profile_name(args.profile) or not _valid_profile_name(args.clone_from):
        print("Profile 名称只能使用小写字母、数字和连字符。", file=stderr)
        return 2

    source = Path(args.source).expanduser().resolve()
    if not (source / "distribution.yaml").is_file():
        print("源目录必须包含 distribution.yaml。", file=stderr)
        return 2
    if not (source / ".git").exists():
        print("本地安装源必须是 Git 工作树。", file=stderr)
        return 2

    try:
        install_profile(
            profile=args.profile,
            clone_from=args.clone_from,
            source=source,
            force=args.force,
            runner=runner or SubprocessRunner(),
            api_port=args.api_port,
        )
    except ValueError as error:
        print(str(error), file=stderr)
        return 2
    except RuntimeError as error:
        print(str(error), file=stderr)
        return 1

    print("Profile `{}` 已安装并完成检查。".format(args.profile), file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
