from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from commitron.cli import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    UPDATE_SOURCE,
    AppError,
    Console,
    Credentials,
    build_parser,
    notify_update,
    request_plan,
    resolve_credentials,
    run_update,
)


class CliConfigurationTests(unittest.TestCase):
    def args(self, *args: str):
        return build_parser().parse_args(list(args))

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key", "OPENAI_API_KEY": "openai-key"}, clear=True)
    def test_openrouter_key_is_preferred_by_default(self) -> None:
        creds = resolve_credentials(self.args())
        self.assertEqual(creds.api_key, "router-key")
        self.assertEqual(creds.base_url, DEFAULT_BASE_URL)
        self.assertEqual(creds.source, "OPENROUTER_API_KEY")

    @patch.dict("os.environ", {"OPENAI_API_KEY": "openai-key"}, clear=True)
    def test_openai_key_selects_openai_endpoint(self) -> None:
        creds = resolve_credentials(self.args())
        self.assertEqual(creds.base_url, "https://api.openai.com/v1")

    @patch.dict("os.environ", {"MY_KEY": "custom-key", "OPENAI_BASE_URL": "https://custom.example/v1/"}, clear=True)
    def test_custom_key_variable_and_url_override(self) -> None:
        creds = resolve_credentials(self.args("--api-key-env", "MY_KEY"))
        self.assertEqual(creds.api_key, "custom-key")
        self.assertEqual(creds.base_url, "https://custom.example/v1")

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}, clear=True)
    def test_rejects_url_embedded_credentials(self) -> None:
        with self.assertRaises(AppError):
            resolve_credentials(self.args("--base-url", "https://user:password@example.test/v1"))

    def test_model_default_and_options(self) -> None:
        args = self.args("--dry-run", "--description", "-y", "--base-url", "https://example.test/v1")
        self.assertTrue(args.dry_run)
        self.assertTrue(args.description)
        self.assertTrue(args.yes)
        self.assertEqual(DEFAULT_MODEL, "openrouter/free")

    @patch("commitron.cli.urllib.request.urlopen")
    def test_openai_compatible_request_and_validated_response(self, urlopen: MagicMock) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"commits": [{"files": ["one.py"], "title": "Add one"}]}
                            )
                        }
                    }
                ]
            }
        ).encode()
        urlopen.return_value = response
        plan = request_plan(
            "diff text",
            ["one.py"],
            Credentials("secret", "https://provider.example/v1", "test"),
            "test-model",
            False,
            10,
        )
        self.assertEqual(plan.commits[0].title, "Add one")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://provider.example/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)


class UpdateCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.console = Console(force_plain=True)

    def test_parser_accepts_update_command(self) -> None:
        args = build_parser().parse_args(["update"])
        self.assertEqual(args.command, "update")

    def test_parser_allows_no_command(self) -> None:
        args = build_parser().parse_args([])
        self.assertIsNone(args.command)

    def test_parser_accepts_no_update_check(self) -> None:
        args = build_parser().parse_args(["--no-update-check"])
        self.assertTrue(args.no_update_check)

    @patch("commitron.cli.check_for_update", return_value="9.9.9")
    def test_notify_update_announces_newer_release(self, check: MagicMock) -> None:
        with patch("commitron.cli.sys.stdout") as stdout, patch("builtins.print") as output:
            stdout.isatty.return_value = True
            notify_update(self.console)
        check.assert_called_once()
        self.assertTrue(output.called)

    @patch("commitron.cli.check_for_update", return_value="9.9.9")
    def test_notify_update_skips_when_not_interactive(self, check: MagicMock) -> None:
        with patch("commitron.cli.sys.stdout") as stdout:
            stdout.isatty.return_value = False
            notify_update(self.console)
        check.assert_not_called()

    @patch("commitron.cli.managed_venv", return_value=None)
    def test_update_requires_managed_install(self, managed: MagicMock) -> None:
        with self.assertRaises(AppError):
            run_update(self.console)

    @patch("commitron.cli.subprocess.run")
    @patch("commitron.cli.installed_version", side_effect=["0.1.0", "0.2.0"])
    @patch("commitron.cli.latest_release_tag", return_value="v0.2.0")
    @patch("commitron.cli.managed_venv")
    def test_update_upgrades_managed_venv(
        self, managed: MagicMock, tag: MagicMock, installed: MagicMock, run: MagicMock
    ) -> None:
        managed.return_value = Path("/tmp/commitron-venv")
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        self.assertEqual(run_update(self.console), 0)
        command = " ".join(run.call_args.args[0])
        self.assertIn("github.com/fardeenes7/commitron", command)
        self.assertIn("@v0.2.0", command)
        self.assertIn("--upgrade", command)
        self.assertIn("--force-reinstall", command)

    @patch("commitron.cli.subprocess.run")
    @patch("commitron.cli.installed_version", side_effect=["0.1.0", "0.2.0"])
    @patch("commitron.cli.latest_release_tag", return_value=None)
    @patch("commitron.cli.managed_venv")
    def test_update_falls_back_to_main_without_release(
        self, managed: MagicMock, tag: MagicMock, installed: MagicMock, run: MagicMock
    ) -> None:
        managed.return_value = Path("/tmp/commitron-venv")
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        self.assertEqual(run_update(self.console), 0)
        command = " ".join(run.call_args.args[0])
        self.assertIn(UPDATE_SOURCE, command)

    @patch("commitron.cli.subprocess.run")
    @patch("commitron.cli.installed_version", side_effect=["0.1.0", "0.1.0"])
    @patch("commitron.cli.latest_release_tag", return_value="v0.1.0")
    @patch("commitron.cli.managed_venv")
    def test_update_reports_when_already_current(
        self, managed: MagicMock, tag: MagicMock, installed: MagicMock, run: MagicMock
    ) -> None:
        managed.return_value = Path("/tmp/commitron-venv")
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        self.assertEqual(run_update(self.console), 0)

    @patch("commitron.cli.subprocess.run")
    @patch("commitron.cli.installed_version", return_value="0.1.0")
    @patch("commitron.cli.latest_release_tag", return_value="v0.2.0")
    @patch("commitron.cli.managed_venv")
    def test_update_reports_pip_failure(
        self, managed: MagicMock, tag: MagicMock, installed: MagicMock, run: MagicMock
    ) -> None:
        managed.return_value = Path("/tmp/commitron-venv")
        run.return_value = MagicMock(returncode=1, stdout="", stderr="network error")
        with self.assertRaises(AppError):
            run_update(self.console)


if __name__ == "__main__":
    unittest.main()
