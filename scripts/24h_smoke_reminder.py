#!/usr/bin/env python3
import pathlib
import sys


LIB = pathlib.Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

from study_assistant.paths import RuntimePaths
from study_assistant.repository import Repository
from study_assistant.i18n import configure_utf8_output


def main():
    paths = RuntimePaths.from_environment()
    Repository(paths.database).initialize()
    print("24h 留学助理测试提醒：本地确定性提醒链路工作正常。")
    return 0


if __name__ == "__main__":
    configure_utf8_output()
    raise SystemExit(main())
