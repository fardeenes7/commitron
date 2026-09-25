from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from commitron.cli import (
    AppError,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    Credentials,
    build_parser,
    request_plan,
    resolve_credentials,
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


if __name__ == "__main__":
    unittest.main()
