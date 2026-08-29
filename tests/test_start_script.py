from __future__ import annotations

import unittest
from pathlib import Path


START_CMD = Path(__file__).resolve().parents[1] / "start.cmd"


class StartScriptTests(unittest.TestCase):
    def test_incomplete_zip_preview_is_rejected_before_setup(self) -> None:
        script = START_CMD.read_text(encoding="utf-8")

        self.assertIn('if not exist "pyproject.toml" goto :incomplete', script)
        self.assertIn('if not exist "src\\tdt_scoring\\api.py" goto :incomplete', script)
        self.assertLess(script.index("goto :incomplete"), script.index("Creating local Python environment"))

    def test_windows_script_uses_only_crlf_line_endings(self) -> None:
        content = START_CMD.read_bytes()

        self.assertIn(b"\r\n", content)
        self.assertNotIn(b"\n", content.replace(b"\r\n", b""))

    def test_runtime_selection_accepts_any_python_312_or_newer(self) -> None:
        script = START_CMD.read_text(encoding="utf-8")

        self.assertIn('sys.version_info >= (3, 12)', script)
        self.assertIn('set "PYTHON_COMMAND=py -3"', script)
        self.assertIn('set "PYTHON_COMMAND=python"', script)
        self.assertIn('set "PYTHON_COMMAND=python3"', script)
        self.assertNotIn('py -3.12 -m venv', script)

    def test_invalid_copied_virtual_environment_has_actionable_error(self) -> None:
        script = START_CMD.read_text(encoding="utf-8")

        self.assertIn('goto :invalid_venv', script)
        self.assertIn('Remove or rename the .venv folder', script)

    def test_existing_service_is_reused_only_when_build_id_matches(self) -> None:
        script = START_CMD.read_text(encoding="utf-8")

        self.assertIn('-m tdt_scoring.launcher', script)
        self.assertIn('for /f "tokens=1,2,3"', script)
        self.assertIn('set "APP_BUILD_ID=', script)
        self.assertIn('if "%LAUNCH_ACTION%"=="reuse" goto :reuse_current', script)
        self.assertIn('set "APP_PORT=', script)
        self.assertIn('/?build=%APP_BUILD_ID%', script)

    def test_service_exit_is_logged_and_keeps_the_window_open(self) -> None:
        script = START_CMD.read_text(encoding="utf-8")

        self.assertIn('if not exist "output" mkdir "output"', script)
        self.assertIn(
            'set "SERVICE_LOG=output\\local-service-%APP_PORT%-%APP_BUILD_ID%-%RANDOM%.log"',
            script,
        )
        self.assertNotIn('set "SERVICE_LOG=output\\local-service.log"', script)
        self.assertIn('goto :log_failed', script)
        self.assertIn(':log_failed', script)
        self.assertIn('>>"%SERVICE_LOG%" 2>&1', script)
        self.assertNotIn("Tee-Object", script)
        self.assertIn('set "SERVER_EXIT_CODE=%ERRORLEVEL%"', script)
        self.assertIn("Local scoring service exited with code", script)
        self.assertIn("Restart start.cmd and use the newly opened page", script)
        self.assertIn("Re-import the review workbook before scoring", script)
        launch_section = script[script.index("\n:launch\n") : script.index("\n:incomplete\n")]
        self.assertIn("pause", launch_section)

    def test_browser_opens_only_after_the_current_service_is_healthy(self) -> None:
        script = START_CMD.read_text(encoding="utf-8")

        self.assertIn("Invoke-RestMethod", script)
        self.assertIn("$health.project_id -eq 'tdt-expert-review-quality'", script)
        self.assertIn("$health.build_id -eq '%APP_BUILD_ID%'", script)
        self.assertIn("Start-Process $url", script)
        self.assertNotIn("Start-Sleep -Seconds 2; Start-Process", script)


if __name__ == "__main__":
    unittest.main()
