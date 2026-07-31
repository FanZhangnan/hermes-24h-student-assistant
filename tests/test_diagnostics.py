import json
import pathlib
import tempfile
import unittest
from urllib.error import HTTPError

from lib.study_assistant.diagnostics import (
    run_diagnostics,
    verify_model,
    verify_vision,
    write_red_vision_fixture,
)
from lib.study_assistant.hermes import CommandResult, HermesRunner
from lib.study_assistant.repository import Repository


class FakeRunner:
    def __init__(self, overrides=None):
        self.calls = []
        self.outputs = {
            ("--version",): CommandResult(0, "Hermes Agent v0.19.0", ""),
            ("config", "check"): CommandResult(0, "Configuration valid", ""),
            ("gateway", "status", "--deep"): CommandResult(0, "Status: running", ""),
            ("cron", "status"): CommandResult(0, "Scheduler: running", ""),
            ("status",): CommandResult(
                0,
                "Model: grok-4.5\nProvider: custom\n"
                "API Keys:\nOPENAI_API_KEY: sk-do-not-retain\n",
                "",
            ),
            ("send", "--list"): CommandResult(0, "telegram\ndiscord", ""),
            (
                "config", "get", "platforms.api_server.extra.port",
            ): CommandResult(0, "8642\n", ""),
        }
        self.outputs.update(overrides or {})

    def run(self, *args):
        self.calls.append(args)
        return self.outputs[args]


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def successful_loopback_opener(request, timeout):
    if request.full_url.endswith("/health"):
        return FakeResponse(200)
    raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)


class DiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.database = pathlib.Path(self.tempdir.name) / "assistant.db"
        Repository(self.database).initialize()

    def test_reports_supported_runtime_without_echoing_key_material(self):
        report = run_diagnostics(
            FakeRunner(),
            primary_target="telegram",
            database=self.database,
            opener=successful_loopback_opener,
        )

        self.assertTrue(report.ok)
        for name in (
            "hermes_version",
            "config",
            "gateway",
            "cron",
            "model",
            "database",
            "delivery",
            "api_health",
            "api_auth",
        ):
            with self.subTest(check=name):
                self.assertEqual(report.checks[name].status, "pass")
        serialized = report.to_json()
        self.assertNotIn("sk-do-not-retain", serialized)
        self.assertNotIn("OPENAI_API_KEY", serialized)
        self.assertEqual(json.loads(serialized)["checks"]["model"]["detail"],
                         "custom / grok-4.5")
        self.assertIn("已支持", report.checks["hermes_version"].summary)
        self.assertIn("正常", report.checks["gateway"].summary)
        self.assertIn("可用", report.checks["database"].summary)

    def test_reports_legacy_provider_key_without_retaining_config_output(self):
        runner = FakeRunner(
            {
                ("config", "check"): CommandResult(
                    0,
                    "Ignored field provider_key; value sk-private",
                    "",
                )
            }
        )

        report = run_diagnostics(
            runner,
            primary_target="telegram",
            database=self.database,
            opener=successful_loopback_opener,
        )

        self.assertEqual(report.checks["config"].status, "warn")
        self.assertIn("key_env", report.checks["config"].remediation)
        self.assertNotIn("sk-private", report.to_json())
        self.assertTrue(report.ok)

    def test_failed_legacy_provider_check_still_recommends_key_env(self):
        runner = FakeRunner(
            {
                ("config", "check"): CommandResult(
                    1,
                    "Unknown field provider_key",
                    "",
                )
            }
        )

        report = run_diagnostics(
            runner,
            primary_target="telegram",
            database=self.database,
            opener=successful_loopback_opener,
        )

        self.assertEqual(report.checks["config"].status, "fail")
        self.assertIn("key_env", report.checks["config"].remediation)

    def test_rejects_non_loopback_api_server_without_opening_it(self):
        def forbidden_opener(request, timeout):
            self.fail("non-loopback URL must not be opened")

        report = run_diagnostics(
            FakeRunner(),
            primary_target="telegram",
            database=self.database,
            api_base_url="https://example.com:8642",
            opener=forbidden_opener,
        )

        self.assertFalse(report.ok)
        self.assertEqual(report.checks["api_health"].status, "fail")
        self.assertEqual(report.checks["api_auth"].status, "fail")

    def test_uses_the_profile_configured_api_server_port(self):
        opened = []

        def configured_port_opener(request, timeout):
            opened.append(request.full_url)
            return successful_loopback_opener(request, timeout)

        runner = FakeRunner(
            {
                (
                    "config", "get", "platforms.api_server.extra.port",
                ): CommandResult(0, "8643\n", "")
            }
        )

        report = run_diagnostics(
            runner,
            primary_target="telegram",
            database=self.database,
            opener=configured_port_opener,
        )

        self.assertTrue(report.ok)
        self.assertEqual(
            opened,
            ["http://127.0.0.1:8643/health", "http://127.0.0.1:8643/v1/models"],
        )

    def test_unsupported_hermes_version_fails(self):
        report = run_diagnostics(
            FakeRunner({("--version",): CommandResult(0, "Hermes Agent v0.18.9", "")}),
            primary_target="telegram",
            database=self.database,
            opener=successful_loopback_opener,
        )

        self.assertFalse(report.ok)
        self.assertEqual(report.checks["hermes_version"].status, "fail")

    def test_historical_running_log_does_not_mask_stopped_services(self):
        runner = FakeRunner(
            {
                ("gateway", "status", "--deep"): CommandResult(
                    0,
                    "Gateway service is not loaded\nRecent logs:\nGateway running with 1 platform",
                    "",
                ),
                ("cron", "status"): CommandResult(
                    0,
                    "Gateway is not running - cron jobs will NOT fire",
                    "",
                ),
            }
        )

        report = run_diagnostics(
            runner,
            primary_target="telegram",
            database=self.database,
            opener=successful_loopback_opener,
        )

        self.assertEqual(report.checks["gateway"].status, "fail")
        self.assertEqual(report.checks["cron"].status, "fail")

    def test_enabled_cron_job_with_missing_script_fails(self):
        hermes_home = pathlib.Path(self.tempdir.name) / "hermes"
        (hermes_home / "cron").mkdir(parents=True)
        (hermes_home / "scripts").mkdir()
        (hermes_home / "cron" / "jobs.json").write_text(
            json.dumps(
                {
                    "jobs": [
                        {
                            "id": "missing-script-job",
                            "name": "损坏的课前提醒",
                            "enabled": True,
                            "script": "missing.py",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = run_diagnostics(
            FakeRunner(),
            primary_target="telegram",
            database=self.database,
            hermes_home=hermes_home,
            opener=successful_loopback_opener,
        )

        self.assertFalse(report.ok)
        self.assertEqual(report.checks["cron_scripts"].status, "fail")
        self.assertIn("missing.py", report.checks["cron_scripts"].detail)
        self.assertNotIn("missing-script-job", report.checks["cron_scripts"].detail)

    def test_paused_cron_job_with_missing_script_warns(self):
        hermes_home = pathlib.Path(self.tempdir.name) / "hermes"
        (hermes_home / "cron").mkdir(parents=True)
        (hermes_home / "scripts").mkdir()
        (hermes_home / "cron" / "jobs.json").write_text(
            json.dumps(
                {
                    "jobs": [
                        {
                            "id": "paused-missing-script-job",
                            "name": "已暂停的损坏提醒",
                            "enabled": False,
                            "state": "paused",
                            "script": "paused-missing.py",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = run_diagnostics(
            FakeRunner(),
            primary_target="telegram",
            database=self.database,
            hermes_home=hermes_home,
            opener=successful_loopback_opener,
        )

        self.assertTrue(report.ok)
        self.assertEqual(report.checks["cron_scripts"].status, "warn")
        self.assertIn("paused-missing.py", report.checks["cron_scripts"].detail)

    def test_online_probes_use_explicit_minimal_commands(self):
        image_path = pathlib.Path("/tmp/red.png")
        runner = FakeRunner(
            {
                (
                    "chat", "--quiet", "--source", "tool", "--query",
                    "Reply with exactly MODEL_OK",
                ): CommandResult(0, "MODEL_OK", ""),
                (
                    "chat", "--quiet", "--source", "tool", "--image", str(image_path),
                    "--query", "Reply with exactly VISION_OK if the image is a solid red square",
                ): CommandResult(0, "VISION_OK", ""),
            }
        )

        self.assertEqual(verify_model(runner).stdout, "MODEL_OK")
        self.assertEqual(verify_vision(runner, image_path).stdout,
                         "VISION_OK")

    def test_red_vision_fixture_is_a_small_png(self):
        path = pathlib.Path(self.tempdir.name) / "red.png"
        write_red_vision_fixture(path)

        payload = path.read_bytes()
        self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
        self.assertLess(len(payload), 1024)

    def test_runner_reports_missing_executable_without_subprocess(self):
        result = HermesRunner(executable="").run("status")
        self.assertEqual(result.returncode, 127)
        self.assertIn("未找到", result.stderr)


if __name__ == "__main__":
    unittest.main()
