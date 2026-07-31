import io
import pathlib
import tempfile
import unittest

from lib.study_assistant.hermes import CommandResult
from tools import install_local


class FakeRunner:
    def __init__(self, profiles="◆default", version="Hermes Agent v0.19.0"):
        self.calls = []
        self.profiles = profiles
        self.version = version

    def run(self, *args):
        self.calls.append(args)
        if args == ("hermes", "--version"):
            return CommandResult(0, self.version, "")
        if args == ("hermes", "profile", "list"):
            return CommandResult(0, self.profiles, "")
        return CommandResult(0, "ok", "")


class InstallLocalTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.source = pathlib.Path(self.tempdir.name) / "project"
        self.source.mkdir()
        (self.source / "distribution.yaml").write_text(
            "name: 24h-assistant\nversion: 0.1.0\n",
            encoding="utf-8",
        )
        (self.source / ".git").write_text("gitdir: test-only\n", encoding="utf-8")
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def invoke(self, runner, force=False):
        argv = [
            "--profile", "24h-assistant",
            "--clone-from", "default",
            "--source", str(self.source),
        ]
        if force:
            argv.append("--force")
        return install_local.main(
            argv,
            stdout=self.stdout,
            stderr=self.stderr,
            runner=runner,
        )

    def test_new_profile_is_cloned_overlaid_and_checked_in_order(self):
        runner = FakeRunner()

        code = self.invoke(runner)

        self.assertEqual(code, 0)
        self.assertEqual(
            runner.calls,
            [
                ("hermes", "--version"),
                ("hermes", "profile", "list"),
                (
                    "hermes", "profile", "create", "24h-assistant",
                    "--clone-from", "default",
                ),
                (
                    "hermes", "profile", "install", str((self.source / ".git").resolve()),
                    "--name", "24h-assistant", "--force", "--yes",
                ),
                (
                    "24h-assistant", "config", "set",
                    "platforms.api_server.extra.port", "8643",
                ),
                ("24h-assistant", "doctor"),
            ],
        )

    def test_existing_profile_requires_force_and_skips_creation(self):
        runner = FakeRunner(profiles="◆default\n  24h-assistant  grok-4.5")

        refused = self.invoke(runner)
        self.assertEqual(refused, 2)
        self.assertEqual(len(runner.calls), 2)

        runner.calls.clear()
        accepted = self.invoke(runner, force=True)
        self.assertEqual(accepted, 0)
        self.assertNotIn(
            (
                "hermes", "profile", "create", "24h-assistant",
                "--clone-from", "default",
            ),
            runner.calls,
        )
        self.assertIn(
            (
                "hermes", "profile", "install", str((self.source / ".git").resolve()),
                "--name", "24h-assistant", "--force", "--yes",
            ),
            runner.calls,
        )
        self.assertNotIn(
            (
                "24h-assistant", "config", "set",
                "platforms.api_server.extra.port", "8643",
            ),
            runner.calls,
        )

    def test_installer_never_handles_credential_files(self):
        source = pathlib.Path(install_local.__file__).read_text(encoding="utf-8")
        self.assertNotIn("open('.env", source)
        self.assertNotIn('open(".env', source)
        self.assertNotIn("auth.json", source)
        self.assertNotIn("shell=True", source)

    def test_unsupported_hermes_version_stops_before_profile_changes(self):
        runner = FakeRunner(version="Hermes Agent v0.18.9")

        code = self.invoke(runner)

        self.assertEqual(code, 1)
        self.assertEqual(runner.calls, [("hermes", "--version")])

    def test_platform_wrappers_only_delegate_to_python_installer(self):
        root = pathlib.Path(install_local.__file__).resolve().parent
        shell_wrapper = (root / "install_local.sh").read_text(encoding="utf-8")
        powershell_wrapper = (root / "install_local.ps1").read_text(encoding="utf-8")
        self.assertIn('python3 "$(cd "$(dirname "$0")" && pwd)/install_local.py" "$@"',
                      shell_wrapper)
        self.assertIn(
            'python (Join-Path $PSScriptRoot "install_local.py") @args',
            powershell_wrapper,
        )

    def test_installer_help_success_and_errors_are_chinese(self):
        help_stdout = io.StringIO()
        help_stderr = io.StringIO()
        self.assertEqual(
            install_local.main(
                ["--help"],
                stdout=help_stdout,
                stderr=help_stderr,
                runner=FakeRunner(),
            ),
            0,
        )
        self.assertIn("安装", help_stdout.getvalue())
        self.assertIn("参数", help_stdout.getvalue())

        success_stdout = io.StringIO()
        self.assertEqual(
            install_local.main(
                [
                    "--profile", "24h-assistant",
                    "--clone-from", "default",
                    "--source", str(self.source),
                ],
                stdout=success_stdout,
                stderr=io.StringIO(),
                runner=FakeRunner(),
            ),
            0,
        )
        self.assertIn("已安装并完成检查", success_stdout.getvalue())

        version_stderr = io.StringIO()
        self.assertEqual(
            install_local.main(
                [
                    "--profile", "24h-assistant",
                    "--clone-from", "default",
                    "--source", str(self.source),
                ],
                stdout=io.StringIO(),
                stderr=version_stderr,
                runner=FakeRunner(version="Hermes Agent v0.18.9"),
            ),
            1,
        )
        self.assertIn("需要 Hermes Agent 0.19.0 或更高版本", version_stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
