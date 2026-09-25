"""Self-update and release-check helpers for Commitron.

Network access here is always optional and best-effort: update checks use a short
timeout and an on-disk cache (at most once per day) so normal runs do not
repeatedly contact GitHub. Every function is safe to call when offline.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY = "fardeenes7/commitron"
_REPOSITORY_URL = f"git+https://github.com/{REPOSITORY}.git"


def update_source(tag: str | None = None) -> str:
    """Return a pip VCS source pinned to a release tag, or main when no release exists."""
    return f"{_REPOSITORY_URL}@{tag or 'main'}"


UPDATE_SOURCE = update_source()
_RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
_TAGS_API = f"https://api.github.com/repos/{REPOSITORY}/tags"
_CACHE_TTL_SECONDS = 24 * 60 * 60
_DEFAULT_TIMEOUT = 1.5
_USER_AGENT = "commitron-update-check"


def parse_version(value: str) -> tuple[int, ...]:
    """Parse the numeric components of a version or tag such as 'v1.2.3'."""
    match = re.match(r"v?(\d+(?:\.\d+)*)", value.strip())
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate: str, current: str) -> bool:
    """Return True when candidate is strictly newer than current."""
    latest = parse_version(candidate)
    installed = parse_version(current)
    if not latest or not installed:
        return False
    length = max(len(latest), len(installed))
    latest += (0,) * (length - len(latest))
    installed += (0,) * (length - len(installed))
    return latest > installed


def managed_venv() -> Path | None:
    """Return the virtual environment created by install.sh when this process runs from it."""
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    candidate = (data_home / "commitron" / "venv").resolve()
    if Path(sys.prefix).resolve() == candidate and (candidate / "pyvenv.cfg").is_file():
        return candidate
    return None


def installed_version(python: Path) -> str | None:
    """Read the version of Commitron installed in the given interpreter, if any."""
    try:
        result = subprocess.run(
            [str(python), "-c", "import commitron; print(commitron.__version__)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def checks_enabled() -> bool:
    """Return False when the user disabled automatic update checks via the environment."""
    for name in ("COMMITRON_NO_UPDATE_CHECK", "NO_UPDATE_NOTIFIER"):
        value = os.environ.get(name)
        if value is not None and value.strip().lower() not in {"", "0", "false", "no", "off"}:
            return False
    return True


def _cache_path() -> Path:
    cache_home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return cache_home / "commitron" / "update-check.json"


def _read_cache() -> dict[str, Any]:
    try:
        value = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_cache(checked_at: float, latest: str | None) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"checked_at": checked_at, "latest": latest}), encoding="utf-8"
        )
    except OSError:
        # A read-only or missing cache directory must never affect the user's command.
        pass


def _fetch_latest_version(timeout: float) -> str | None:
    """Query the public GitHub releases (then tags) API for the newest version."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
    }
    for url in (_RELEASES_API, _TAGS_API):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("tag_name"), str):
            return payload["tag_name"]
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            name = payload[0].get("name")
            if isinstance(name, str):
                return name
    return None


def latest_release_tag(timeout: float = _DEFAULT_TIMEOUT) -> str | None:
    """Return the newest published release/tag name, or None when unavailable."""
    return _fetch_latest_version(timeout)


def check_for_update(
    current: str,
    timeout: float = _DEFAULT_TIMEOUT,
    ttl: float = _CACHE_TTL_SECONDS,
) -> str | None:
    """Return the newest published version when it is newer than current, else None."""
    if not checks_enabled():
        return None
    now = time.time()
    cache = _read_cache()
    checked_at = cache.get("checked_at")
    latest = cache.get("latest")
    fresh = isinstance(checked_at, (int, float)) and now - checked_at < ttl
    if not fresh:
        fetched = _fetch_latest_version(timeout)
        if fetched is not None:
            latest = fetched
        # Cache failures too, so an offline machine is not retried on every run.
        _write_cache(now, latest if isinstance(latest, str) else None)
    if isinstance(latest, str) and is_newer(latest, current):
        return latest
    return None
