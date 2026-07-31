#!/usr/bin/env python3
import pathlib
import sys


LIB = pathlib.Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

from study_assistant.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
