#!/usr/bin/env python3
"""在 Hermes 安装或公开发布前执行不泄露敏感值的确定性检查。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


SKIP_DIRECTORIES = {
    ".git",
    ".worktrees",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
}
TEXT_SIZE_LIMIT = 2 * 1024 * 1024
TOKEN_PATTERN = re.compile(r"[\w.-]+", re.UNICODE)
PERSONAL_PATH_PATTERNS = (
    re.compile("/" + r"Users/[^/\s]+/"),
    re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+\\"),
)
SECRET_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?<!\d)\d{8,10}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    message: str


@dataclass(frozen=True)
class AuditReport:
    findings: tuple

    @property
    def ok(self):
        return not self.findings

    def to_dict(self):
        return {
            "ok": self.ok,
            "findings": [asdict(finding) for finding in self.findings],
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    def to_text(self):
        if self.ok:
            return "发布守门检查通过"
        lines = ["发布守门检查失败："]
        for finding in self.findings:
            lines.append("- [{}] {}：{}".format(
                finding.rule,
                finding.path,
                finding.message,
            ))
        return "\n".join(lines)


def _relative(path, root):
    return path.relative_to(root).as_posix()


def _iter_files(root):
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRECTORIES for part in path.relative_to(root).parts):
            continue
        if path.is_file() and not path.is_symlink():
            yield path


def _runtime_state_rule(relative):
    path = Path(relative)
    name = path.name
    if name == ".env.example" or name == "config.example.yaml":
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    if name in {"auth.json", "config.yaml", "gateway.pid", "cron/jobs.json"}:
        return True
    if name.endswith((".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3")):
        return True
    parts = path.parts
    return len(parts) >= 2 and parts[0] == "data" and parts[1] in {
        "calendar",
        "courses",
    }


def _load_denylist(root):
    path = root / "privacy_denylist.sha256"
    if not path.is_file():
        return set(), None
    hashes = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip().casefold()
        if not value or value.startswith("#"):
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            return set(), Finding(
                "denylist_format",
                "privacy_denylist.sha256",
                "隐私哈希清单格式无效",
            )
        hashes.add(value)
    return hashes, None


def _hashed_private_identifier(text, denylist):
    for token in TOKEN_PATTERN.findall(text.casefold()):
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if digest in denylist:
            return True
    return False


def _read_text(path):
    try:
        if path.stat().st_size > TEXT_SIZE_LIMIT:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _contract_findings(root):
    contract_path = root / "cron_contract.json"
    if not contract_path.is_file():
        return [Finding(
            "cron_contract",
            "cron_contract.json",
            "缺少确定性 Cron 脚本契约",
        )]
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
        scripts = payload["scripts"]
        if payload.get("version") != 1 or not isinstance(scripts, list):
            raise (ValueError("invalid contract"))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return [Finding(
            "cron_contract",
            "cron_contract.json",
            "Cron 脚本契约格式无效",
        )]

    findings = []
    for script in scripts:
        if not isinstance(script, str) or Path(script).name != script:
            findings.append(Finding(
                "cron_contract",
                "cron_contract.json",
                "Cron 契约包含无效脚本名",
            ))
            continue
        relative = "scripts/{}".format(script)
        if not (root / relative).is_file():
            findings.append(Finding(
                "cron_contract",
                relative,
                "契约声明的脚本不存在",
            ))
    return findings


def _profile_findings(root, profile):
    if profile is None:
        return []
    jobs_path = Path(profile) / "cron" / "jobs.json"
    if not jobs_path.is_file():
        return []
    try:
        payload = json.loads(jobs_path.read_text(encoding="utf-8"))
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
        if not isinstance(jobs, list):
            raise ValueError("jobs must be a list")
    except (OSError, json.JSONDecodeError, ValueError):
        return [Finding(
            "profile_cron",
            "cron/jobs.json",
            "无法安全读取 Profile Cron 配置",
        )]

    findings = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        script = job.get("script")
        if not isinstance(script, str) or not script.strip():
            continue
        name = Path(script).name
        if name != script or not (root / "scripts" / name).is_file():
            findings.append(Finding(
                "orphan_cron_script",
                "scripts/{}".format(name or "invalid-script"),
                "Profile 任务在安装后将找不到脚本",
            ))
    return findings


def audit_repository(root, mode, profile=None):
    root = Path(root).expanduser().resolve()
    if mode not in {"private", "public"}:
        raise ValueError("mode 必须是 private 或 public")
    if not root.is_dir():
        return AuditReport((Finding(
            "repository",
            ".",
            "仓库目录不存在",
        ),))

    findings = []
    denylist, denylist_error = _load_denylist(root)
    if denylist_error is not None:
        findings.append(denylist_error)
    for path in _iter_files(root):
        relative = _relative(path, root)
        if _runtime_state_rule(relative):
            findings.append(Finding(
                "runtime_state",
                relative,
                "运行时状态不得进入发行仓库",
            ))
            continue
        if mode == "public" and path.suffix.casefold() == ".log":
            findings.append(Finding(
                "public_log",
                relative,
                "真实或验收日志不得进入公开仓库",
            ))
            continue
        text = _read_text(path)
        if text is None:
            continue
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            findings.append(Finding(
                "secret_pattern",
                relative,
                "文件包含高风险密钥形态",
            ))
        if mode != "public":
            continue
        if any(pattern.search(text) for pattern in PERSONAL_PATH_PATTERNS):
            findings.append(Finding(
                "personal_path",
                relative,
                "文件包含本机用户目录",
            ))
        if denylist and _hashed_private_identifier(text, denylist):
            findings.append(Finding(
                "private_identifier",
                relative,
                "文件包含禁止公开的个人或机构标识",
            ))

    findings.extend(_contract_findings(root))
    findings.extend(_profile_findings(root, profile))
    unique = {
        (finding.rule, finding.path, finding.message): finding for finding in findings
    }
    ordered = tuple(unique[key] for key in sorted(unique))
    return AuditReport(ordered)


def build_parser():
    parser = argparse.ArgumentParser(description="执行 24h 留学助理发布守门检查")
    parser.add_argument("--root", default=".", help="待检查仓库目录")
    parser.add_argument(
        "--mode",
        choices=("private", "public"),
        required=True,
        help="私有开发或公开发布模式",
    )
    parser.add_argument("--profile", help="可选 Hermes Profile 根目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    return parser


def _configure_utf8_output(stream):
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    return stream


def main(argv=None, stdout=None):
    stdout = _configure_utf8_output(stdout or sys.stdout)
    args = build_parser().parse_args(argv)
    report = audit_repository(args.root, args.mode, args.profile)
    print(report.to_json() if args.json else report.to_text(), file=stdout)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
