import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class SmokeScriptTest(unittest.TestCase):
    def test_script_prints_one_deterministic_message_without_network_code(self):
        with tempfile.TemporaryDirectory() as home:
            environment = dict(os.environ, HERMES_HOME=home)
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "24h_assistant.py"), "init"],
                check=True,
                env=environment,
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "24h_smoke_reminder.py")],
                check=True,
                env=environment,
                capture_output=True,
                text=True,
            )

        self.assertEqual(
            result.stdout.strip(),
            "24h 留学助理测试提醒：本地确定性提醒链路工作正常。",
        )
        source = (ROOT / "scripts" / "24h_smoke_reminder.py").read_text(
            encoding="utf-8"
        )
        for forbidden in ("requests", "urllib", "OPENAI_API_KEY", "HermesRunner"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
