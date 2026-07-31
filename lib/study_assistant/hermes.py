import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class HermesRunner:
    def __init__(self, executable=None, timeout=30):
        self.executable = shutil.which("hermes") if executable is None else executable
        self.timeout = timeout

    def run(self, *args):
        if not self.executable:
            return CommandResult(127, "", "未找到 Hermes 可执行文件")
        try:
            completed = subprocess.run(
                [self.executable, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(124, "", "Hermes 命令执行超时")
        except OSError:
            return CommandResult(127, "", "无法启动 Hermes 可执行文件")
        return CommandResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )
