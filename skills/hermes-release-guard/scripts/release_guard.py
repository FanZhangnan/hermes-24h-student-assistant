#!/usr/bin/env python3
"""调用目标仓库自带的确定性发布守门。"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _parser():
    parser = argparse.ArgumentParser(description="调用 Hermes 扩展包发布守门")
    parser.add_argument("--root", required=True, help="目标仓库根目录")
    parser.add_argument("--mode", choices=("private", "public"), required=True)
    parser.add_argument("--profile", help="可选 Hermes Profile 根目录")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    guard = root / "tools" / "release_guard.py"
    if not guard.is_file():
        print("目标仓库缺少 tools/release_guard.py，停止发布。", file=sys.stderr)
        return 2

    command = [
        sys.executable,
        str(guard),
        "--root",
        str(root),
        "--mode",
        args.mode,
    ]
    if args.profile:
        command.extend(("--profile", args.profile))
    if args.json:
        command.append("--json")
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
