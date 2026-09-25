from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from commitron import update


class VersionTests(unittest.TestCase):
    def test_parse_version_handles_tags_and_suffixes(self) -> None:
        self.assertEqual(update.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(update.parse_version("0.2.0"), (0, 2, 0))
        self.assertEqual(update.parse_version("1.0.0-rc1"), (1, 0, 0))
        self.assertEqual(update.parse_version("no digits"), ())

    def test_is_newer(self) -> None:
        self.assertTrue(update.is_newer("0.2.0", "0.1.0"))
        self.assertTrue(update.is_newer("v1.0.0", "0.9.9"))
        self.assertTrue(update.is_newer("1.1", "1.0.9"))
        self.assertFalse(update.is_newer("0.1.0", "0.1.0"))
        self.assertFalse(update.is_newer("0.1.0", "0.2.0"))
        self.assertFalse(update.is_newer("garbage", "0.1.0"))

    def test_update_source_pins_tags_and_falls_back_to_main(self) -> None:
        self.assertTrue(update.update_source("v1.2.3").endswith("@v1.2.3"))
        self.assertTrue(update.update_source().endswith("@main"))

    @patch("commitron.update._fetch_latest_version", return_value="v1.0.0")
    def test_latest_release_tag(self, fetch) -> None:
        self.assertEqual(update.latest_release_tag(), "v1.0.0")


class UpdateCheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._env = patch.dict(
            "os.environ",
            {
                "XDG_CACHE_HOME": self._tmp.name,
                "COMMITRON_NO_UPDATE_CHECK": "",
                "NO_UPDATE_NOTIFIER": "",
            },
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    @property
    def cache_file(self) -> Path:
        return Path(self._tmp.name) / "commitron" / "update-check.json"

    @patch("commitron.update._fetch_latest_version", return_value="0.2.0")
    def test_reports_newer_release_and_caches(self, fetch) -> None:
        self.assertEqual(update.check_for_update("0.1.0"), "0.2.0")
        self.assertTrue(self.cache_file.is_file())
        self.assertEqual(json.loads(self.cache_file.read_text())["latest"], "0.2.0")

    @patch("commitron.update._fetch_latest_version", return_value="0.1.0")
    def test_ignores_same_version(self, fetch) -> None:
        self.assertIsNone(update.check_for_update("0.1.0"))

    @patch("commitron.update._fetch_latest_version", return_value="0.2.0")
    def test_uses_cache_within_ttl(self, fetch) -> None:
        self.assertEqual(update.check_for_update("0.1.0"), "0.2.0")
        self.assertEqual(update.check_for_update("0.1.0"), "0.2.0")
        self.assertEqual(fetch.call_count, 1)

    @patch("commitron.update._fetch_latest_version", return_value=None)
    def test_offline_is_silent_and_backs_off(self, fetch) -> None:
        self.assertIsNone(update.check_for_update("0.1.0"))
        self.assertTrue(self.cache_file.is_file())
        self.assertIsNone(json.loads(self.cache_file.read_text())["latest"])

    @patch("commitron.update._fetch_latest_version", return_value="0.2.0")
    def test_env_var_disables_checks(self, fetch) -> None:
        with patch.dict("os.environ", {"COMMITRON_NO_UPDATE_CHECK": "1"}):
            self.assertIsNone(update.check_for_update("0.1.0"))
        fetch.assert_not_called()

    @patch("commitron.update._fetch_latest_version", return_value="0.2.0")
    def test_no_update_notifier_disables_checks(self, fetch) -> None:
        with patch.dict("os.environ", {"NO_UPDATE_NOTIFIER": "1"}):
            self.assertIsNone(update.check_for_update("0.1.0"))
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
