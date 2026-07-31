import os
from dataclasses import dataclass
from pathlib import Path


# 测试模拟其他操作系统时，仍保留当前主机的具体 Path 类型。
_ConcretePath = type(Path())


@dataclass(frozen=True)
class RuntimePaths:
    hermes_home: Path
    data_dir: Path
    database: Path

    @classmethod
    def from_environment(cls):
        raw_home = os.environ.get("HERMES_HOME")
        if raw_home:
            hermes_home = _ConcretePath(raw_home).expanduser()
        elif os.name == "nt":
            local_app_data = os.environ.get("LOCALAPPDATA")
            if not local_app_data:
                raise RuntimeError("Windows 上必须存在 LOCALAPPDATA 环境变量")
            hermes_home = _ConcretePath(local_app_data) / "hermes"
        else:
            hermes_home = _ConcretePath.home() / ".hermes"

        data_dir = hermes_home / "24h-assistant"
        return cls(
            hermes_home=hermes_home,
            data_dir=data_dir,
            database=data_dir / "assistant.db",
        )
