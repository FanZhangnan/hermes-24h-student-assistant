import ipaddress
import json
import re
import sqlite3
import struct
import urllib.request
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit


@dataclass(frozen=True)
class DiagnosticCheck:
    status: str
    summary: str
    detail: str = None
    remediation: str = None

    def to_dict(self):
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class DiagnosticReport:
    checks: dict

    @property
    def ok(self):
        return all(check.status != "fail" for check in self.checks.values())

    def to_dict(self):
        return {
            "ok": self.ok,
            "checks": {
                name: check.to_dict() for name, check in self.checks.items()
            },
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def _version_check(result):
    match = re.search(r"\bv?(\d+)\.(\d+)\.(\d+)\b", result.stdout)
    if result.returncode != 0 or not match:
        return DiagnosticCheck(
            "fail",
            "无法验证 Hermes 版本",
            remediation="请安装 Hermes Agent 0.19.0 或更高版本。",
        )
    version = tuple(int(part) for part in match.groups())
    if version < (0, 19, 0):
        return DiagnosticCheck(
            "fail",
            "Hermes Agent 版本低于 0.19.0",
            detail=".".join(match.groups()),
            remediation="安装本扩展包前请先更新 Hermes Agent。",
        )
    return DiagnosticCheck(
        "pass",
        "Hermes Agent 版本已支持",
        detail=".".join(match.groups()),
    )


def _config_check(result):
    output = "\n".join((result.stdout, result.stderr))
    legacy_provider_key = re.search(r"\bprovider_key\b", output)
    if result.returncode != 0:
        remediation = (
            "请将模型提供商配置迁移到受支持的 `key_env` 字段。"
            if legacy_provider_key
            else "请运行 `hermes config check` 并修正其报告的配置项。"
        )
        return DiagnosticCheck(
            "fail",
            "Hermes 配置检查失败",
            remediation=remediation,
        )
    if legacy_provider_key:
        return DiagnosticCheck(
            "warn",
            "Hermes 会忽略旧版自定义模型字段 `provider_key`",
            remediation="请将模型提供商配置迁移到受支持的 `key_env` 字段。",
        )
    return DiagnosticCheck("pass", "Hermes 配置有效")


def _gateway_check(result):
    current_status = result.stdout.split("Recent logs:", 1)[0]
    running = any(
        marker in current_status
        for marker in (
            "Status: running",
            "Gateway is supervised by",
            "Gateway is running",
        )
    )
    if result.returncode == 0 and running:
        return DiagnosticCheck("pass", "Gateway 运行正常")
    return DiagnosticCheck(
        "fail",
        "Gateway 未运行",
        remediation="请启动当前 Profile 的 Gateway 服务后重试。",
    )


def _cron_check(result):
    running = any(
        marker in result.stdout
        for marker in (
            "Scheduler: running",
            "Gateway is running — cron jobs will fire automatically",
            "Ticker heartbeat:",
        )
    )
    if result.returncode == 0 and running and "not running" not in result.stdout.lower():
        return DiagnosticCheck("pass", "Cron 调度器运行正常")
    return DiagnosticCheck(
        "fail",
        "Cron 调度器未运行",
        remediation="请启动当前 Profile 的 Gateway 服务后重试。",
    )


def _cron_scripts_check(hermes_home):
    if hermes_home is None:
        return DiagnosticCheck("pass", "未指定 Profile，跳过 Cron 脚本检查")

    root = Path(hermes_home)
    jobs_path = root / "cron" / "jobs.json"
    if not jobs_path.is_file():
        return DiagnosticCheck("pass", "当前 Profile 尚无 Cron 任务")
    try:
        payload = json.loads(jobs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DiagnosticCheck(
            "fail",
            "无法读取 Cron 任务配置",
            remediation="请检查当前 Profile 的 cron/jobs.json。",
        )

    jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
    if not isinstance(jobs, list):
        return DiagnosticCheck(
            "fail",
            "Cron 任务配置格式无效",
            remediation="请检查当前 Profile 的 cron/jobs.json。",
        )

    active_missing = []
    paused_missing = []
    scripts_dir = root / "scripts"
    for job in jobs:
        if not isinstance(job, dict):
            continue
        script = job.get("script")
        if not isinstance(script, str) or not script.strip():
            continue
        relative = Path(script)
        candidate = relative if relative.is_absolute() else scripts_dir / relative
        try:
            exists = candidate.resolve().is_relative_to(scripts_dir.resolve())
            exists = exists and candidate.is_file()
        except (OSError, RuntimeError):
            exists = False
        if exists:
            continue
        display_name = relative.name or "无效脚本名"
        if job.get("enabled") is True:
            active_missing.append(display_name)
        else:
            paused_missing.append(display_name)

    if active_missing:
        return DiagnosticCheck(
            "fail",
            "启用的 Cron 任务引用了不存在的脚本",
            detail=", ".join(sorted(set(active_missing))),
            remediation="请先暂停损坏任务，恢复脚本后再重新启用。",
        )
    if paused_missing:
        return DiagnosticCheck(
            "warn",
            "已暂停的 Cron 任务仍缺少脚本",
            detail=", ".join(sorted(set(paused_missing))),
            remediation="重新启用这些任务前请先恢复对应脚本。",
        )
    return DiagnosticCheck("pass", "Cron 任务引用的脚本均存在")


def _extract_model_check(result):
    if result.returncode != 0:
        return DiagnosticCheck("fail", "无法读取当前模型状态")
    values = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^\s*(Model|Provider):\s*(.*?)\s*$", line, re.I)
        if match and match.group(2):
            values[match.group(1).lower()] = match.group(2)[:120]
    if not values.get("model") or not values.get("provider"):
        return DiagnosticCheck(
            "fail",
            "必须同时配置可用的模型和模型提供商",
            remediation="请在当前 Hermes Profile 中配置产品模型路由。",
        )
    detail = "{} / {}".format(values["provider"], values["model"])
    if re.search(r"(?i)(sk-|api[_ -]?key|bearer\s)", detail):
        return DiagnosticCheck("fail", "当前模型状态无法安全显示")
    return DiagnosticCheck("pass", "已配置可用的模型路由", detail=detail)


def _database_check(database):
    if database is None or not Path(database).is_file():
        return DiagnosticCheck(
            "fail",
            "产品数据库尚未初始化",
            remediation="请在当前 Profile 中运行 `24h_assistant.py init`。",
        )
    try:
        with sqlite3.connect(str(database)) as connection:
            connection.execute("SELECT version FROM schema_migrations LIMIT 1").fetchone()
    except (OSError, sqlite3.Error):
        return DiagnosticCheck(
            "fail",
            "无法访问产品数据库",
            remediation="请检查 Profile 数据目录的权限。",
        )
    return DiagnosticCheck("pass", "产品数据库可用且可正常访问")


def _delivery_check(result, primary_target):
    if not primary_target:
        return DiagnosticCheck(
            "fail",
            "尚未配置主消息投递目标",
            remediation="请在首次设置中保存一个主消息投递目标。",
        )
    if result.returncode != 0 or primary_target not in result.stdout:
        return DiagnosticCheck(
            "fail",
            "Hermes 中当前主消息投递目标不可用",
            remediation="请使用 `hermes gateway setup` 配置该目标。",
        )
    return DiagnosticCheck("pass", "主消息投递目标可用")


def _is_loopback_base_url(base_url):
    try:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return False
        if parsed.path not in {"", "/"}:
            return False
        if parsed.hostname.lower() == "localhost":
            return True
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


def _api_checks(base_url, opener):
    invalid = DiagnosticCheck(
        "fail",
        "API Server URL 不是仅本机回环地址",
        remediation="请使用 http://127.0.0.1:8642 等本机回环 URL。",
    )
    if not _is_loopback_base_url(base_url):
        return invalid, invalid

    root = base_url.rstrip("/")
    try:
        health_request = urllib.request.Request(root + "/health", method="GET")
        with opener(health_request, timeout=3) as response:
            health_status = response.status
    except (HTTPError, URLError, OSError):
        health_status = None

    health = (
        DiagnosticCheck("pass", "本机回环 API Server 运行正常")
        if health_status == 200
        else DiagnosticCheck(
            "fail",
            "本机回环 API Server 健康检查失败",
            remediation="请启动当前 Profile 的 API Server 后重试。",
        )
    )

    try:
        models_request = urllib.request.Request(root + "/v1/models", method="GET")
        with opener(models_request, timeout=3) as response:
            models_status = response.status
    except HTTPError as error:
        models_status = error.code
    except (URLError, OSError):
        models_status = None

    authentication = (
        DiagnosticCheck("pass", "API Server 已拒绝未认证的模型访问")
        if models_status == 401
        else DiagnosticCheck(
            "fail",
            "未验证 API Server 认证边界",
            remediation="请确保 /v1 端点必须提供 API_SERVER_KEY。",
        )
    )
    return health, authentication


def _configured_api_base_url(runner):
    result = runner.run("config", "get", "platforms.api_server.extra.port")
    value = result.stdout.strip()
    if result.returncode == 0 and value.isdigit() and 1 <= int(value) <= 65535:
        return "http://127.0.0.1:{}".format(value)
    return "http://127.0.0.1:8642"


def run_diagnostics(
    runner,
    primary_target=None,
    database=None,
    hermes_home=None,
    api_base_url=None,
    opener=urllib.request.urlopen,
):
    version = runner.run("--version")
    config = runner.run("config", "check")
    gateway = runner.run("gateway", "status", "--deep")
    cron = runner.run("cron", "status")
    status = runner.run("status")
    destinations = runner.run("send", "--list")
    if api_base_url is None:
        api_base_url = _configured_api_base_url(runner)
    api_health, api_auth = _api_checks(api_base_url, opener)

    checks = {
        "hermes_version": _version_check(version),
        "config": _config_check(config),
        "gateway": _gateway_check(gateway),
        "cron": _cron_check(cron),
        "cron_scripts": _cron_scripts_check(hermes_home),
        "model": _extract_model_check(status),
        "database": _database_check(database),
        "delivery": _delivery_check(destinations, primary_target),
        "api_health": api_health,
        "api_auth": api_auth,
    }
    return DiagnosticReport(checks)


def verify_model(runner):
    return runner.run(
        "chat",
        "--quiet",
        "--source",
        "tool",
        "--query",
        "Reply with exactly MODEL_OK",
    )


def write_red_vision_fixture(path):
    width = height = 32
    rows = b"".join(b"\x00" + (b"\xff\x00\x00" * width) for _ in range(height))

    def chunk(kind, payload):
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows))
    png += chunk(b"IEND", b"")
    Path(path).write_bytes(png)


def verify_vision(runner, image_path):
    return runner.run(
        "chat",
        "--quiet",
        "--source",
        "tool",
        "--image",
        str(image_path),
        "--query",
        "Reply with exactly VISION_OK if the image is a solid red square",
    )
