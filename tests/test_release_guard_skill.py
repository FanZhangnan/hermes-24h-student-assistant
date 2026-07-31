import importlib.util
import io
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "hermes-release-guard" / "scripts" / "release_guard.py"


def load_wrapper():
    spec = importlib.util.spec_from_file_location("release_guard_skill_wrapper", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseGuardSkillTest(unittest.TestCase):
    def test_missing_repository_guard_stops_release(self):
        module = load_wrapper()
        with tempfile.TemporaryDirectory() as tempdir:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = module.main(["--root", tempdir, "--mode", "public"])

        self.assertEqual(code, 2)
        self.assertIn("停止发布", stderr.getvalue())

    def test_wrapper_delegates_without_shell_or_output_capture(self):
        module = load_wrapper()
        with tempfile.TemporaryDirectory() as tempdir:
            root = pathlib.Path(tempdir)
            guard = root / "tools" / "release_guard.py"
            guard.parent.mkdir()
            guard.write_text("# test fixture\n", encoding="utf-8")
            resolved_root = root.resolve()
            resolved_guard = resolved_root / "tools" / "release_guard.py"

            with patch.object(module.subprocess, "run") as run:
                run.return_value.returncode = 0
                code = module.main(
                    [
                        "--root",
                        str(root),
                        "--mode",
                        "private",
                        "--profile",
                        str(root / "profile"),
                        "--json",
                    ]
                )

        self.assertEqual(code, 0)
        run.assert_called_once_with(
            [
                sys.executable,
                str(resolved_guard),
                "--root",
                str(resolved_root),
                "--mode",
                "private",
                "--profile",
                str(root / "profile"),
                "--json",
            ],
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
