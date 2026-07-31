import hashlib
import io
import json
import pathlib
import tempfile
import unittest

from tools import release_guard
from tools.release_guard import audit_repository, main


class ReleaseGuardTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = pathlib.Path(self.tempdir.name) / "repository"
        self.root.mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "reminder.py").write_text(
            "print('demo reminder')\n",
            encoding="utf-8",
        )
        (self.root / "cron_contract.json").write_text(
            json.dumps({"version": 1, "scripts": ["reminder.py"]}),
            encoding="utf-8",
        )
        (self.root / "privacy_denylist.sha256").write_text("", encoding="utf-8")
        (self.root / "README.md").write_text(
            "# Generic student assistant\n",
            encoding="utf-8",
        )

    def test_cli_reconfigures_ascii_stream_for_chinese_output(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="ascii")

        code = main(
            ["--root", str(self.root), "--mode", "public"],
            stdout=stream,
        )
        stream.flush()

        self.assertEqual(code, 0)
        self.assertIn("发布守门检查通过", buffer.getvalue().decode("utf-8"))

    def test_safe_public_repository_passes(self):
        report = audit_repository(self.root, "public")

        self.assertTrue(report.ok)
        self.assertEqual(report.findings, ())
        self.assertTrue(json.loads(report.to_json())["ok"])

    def test_public_mode_rejects_personal_paths_logs_and_runtime_files(self):
        (self.root / "notes.md").write_text(
            "Installed from " + "/" + "Users/private-user/project\n",
            encoding="utf-8",
        )
        (self.root / "acceptance.log").write_text("passed\n", encoding="utf-8")
        (self.root / "assistant.db").write_bytes(b"sqlite")

        report = audit_repository(self.root, "public")

        self.assertFalse(report.ok)
        rules = {finding.rule for finding in report.findings}
        self.assertEqual(
            rules,
            {"personal_path", "public_log", "runtime_state"},
        )
        self.assertNotIn("private-user", report.to_json())

    def test_release_guard_source_does_not_trigger_its_personal_path_rule(self):
        source = pathlib.Path(release_guard.__file__).read_text(encoding="utf-8")

        self.assertFalse(
            any(pattern.search(source) for pattern in release_guard.PERSONAL_PATH_PATTERNS)
        )

    def test_public_mode_rejects_hashed_private_identifiers_without_storing_value(self):
        private_marker = "PrivateUniversity"
        digest = hashlib.sha256(private_marker.casefold().encode("utf-8")).hexdigest()
        (self.root / "privacy_denylist.sha256").write_text(
            digest + "\n",
            encoding="utf-8",
        )
        (self.root / "README.md").write_text(
            "This build contains PrivateUniversity fixtures.\n",
            encoding="utf-8",
        )

        report = audit_repository(self.root, "public")

        self.assertFalse(report.ok)
        self.assertEqual(report.findings[0].rule, "private_identifier")
        self.assertNotIn(private_marker, report.to_json())

    def test_contract_rejects_missing_distribution_script(self):
        (self.root / "cron_contract.json").write_text(
            json.dumps({"version": 1, "scripts": ["missing.py"]}),
            encoding="utf-8",
        )

        report = audit_repository(self.root, "private")

        self.assertFalse(report.ok)
        self.assertEqual(report.findings[0].rule, "cron_contract")
        self.assertEqual(report.findings[0].path, "scripts/missing.py")

    def test_profile_rejects_cron_script_missing_after_install(self):
        profile = pathlib.Path(self.tempdir.name) / "profile"
        (profile / "cron").mkdir(parents=True)
        (profile / "cron" / "jobs.json").write_text(
            json.dumps(
                {
                    "jobs": [
                        {
                            "id": "private-job-id",
                            "enabled": True,
                            "script": "removed.py",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        report = audit_repository(self.root, "private", profile)

        self.assertFalse(report.ok)
        self.assertEqual(report.findings[0].rule, "orphan_cron_script")
        self.assertEqual(report.findings[0].path, "scripts/removed.py")
        self.assertNotIn("private-job-id", report.to_json())

    def test_private_mode_allows_school_overlays_and_verification_logs(self):
        marker = "PrivateUniversity"
        digest = hashlib.sha256(marker.casefold().encode("utf-8")).hexdigest()
        (self.root / "privacy_denylist.sha256").write_text(
            digest + "\n",
            encoding="utf-8",
        )
        verification = self.root / "docs" / "verification"
        verification.mkdir(parents=True)
        (verification / "acceptance.log").write_text(
            marker + " accepted\n",
            encoding="utf-8",
        )

        report = audit_repository(self.root, "private")

        self.assertTrue(report.ok)

    def test_json_cli_returns_failure_without_echoing_secret_value(self):
        secret = "123456789:" + "abcdefghijklmnopqrstuvwxyzABCDEFG"
        (self.root / "unsafe.txt").write_text(secret, encoding="utf-8")
        output = pathlib.Path(self.tempdir.name) / "output.txt"

        with output.open("w", encoding="utf-8") as stream:
            code = main(
                ["--root", str(self.root), "--mode", "public", "--json"],
                stdout=stream,
            )

        rendered = output.read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertIn("secret_pattern", rendered)
        self.assertNotIn(secret, rendered)


if __name__ == "__main__":
    unittest.main()
