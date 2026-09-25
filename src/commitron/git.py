"""Git snapshotting and isolated multi-commit creation."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class GitError(Exception):
    """A Git operation failed."""


@dataclass(frozen=True)
class PlannedCommit:
    files: list[str]
    title: str
    description: str = ""


@dataclass(frozen=True)
class CommitPlan:
    commits: list[PlannedCommit]

    @classmethod
    def from_json(
        cls, value: dict[str, Any], changed_files: list[str], include_description: bool
    ) -> CommitPlan:
        raw_commits = value.get("commits")
        if not isinstance(raw_commits, list) or not raw_commits:
            raise GitError("The API plan must contain a non-empty 'commits' array.")
        allowed = set(changed_files)
        assigned: list[str] = []
        commits: list[PlannedCommit] = []
        for number, item in enumerate(raw_commits, start=1):
            if not isinstance(item, dict):
                raise GitError(f"Commit {number} in the API plan is not an object.")
            files = item.get("files")
            title = item.get("title")
            description = item.get("description", "")
            if not isinstance(files, list) or not files or any(not isinstance(path, str) for path in files):
                raise GitError(f"Commit {number} must list one or more file paths.")
            if (
                not isinstance(title, str)
                or not title.strip()
                or any(
                    ord(char) < 32
                    or ord(char) == 127
                    or unicodedata.category(char) in {"Zl", "Zp"}
                    for char in title
                )
            ):
                raise GitError(f"Commit {number} must have a non-empty, single-line title.")
            if include_description and not isinstance(description, str):
                raise GitError(f"Commit {number} description must be a string.")
            if include_description and any(
                ((ord(char) < 32 and char not in "\n\t")
                or ord(char) == 127
                or unicodedata.category(char) in {"Zl", "Zp"})
                for char in description
            ):
                raise GitError(f"Commit {number} description contains unsupported control characters.")
            if not include_description:
                description = ""
            for path in files:
                if path not in allowed:
                    raise GitError(f"The API included a path that is not changed: {path!r}.")
                if path in assigned:
                    raise GitError(f"The API assigned a changed path more than once: {path!r}.")
                assigned.append(path)
            commits.append(PlannedCommit(files, title.strip(), description.strip()))
        missing = allowed - set(assigned)
        if missing:
            formatted = ", ".join(repr(path) for path in sorted(missing))
            raise GitError(f"The API omitted changed path(s): {formatted}.")
        if len(assigned) != len(changed_files):
            raise GitError("The API plan does not contain each changed path exactly once.")
        return cls(commits)


@dataclass
class Snapshot:
    diff: str
    diff_size_bytes: int
    files: list[str]
    index_path: str
    base_head: str
    real_index_signature: bytes

    def close(self) -> None:
        try:
            os.unlink(self.index_path)
        except FileNotFoundError:
            pass


class GitRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.real_index_preserved = False

    @staticmethod
    def _run(
        args: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        input_data: bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=cwd,
                env=env,
                input=input_data,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GitError("Git is not installed or is not on PATH.") from exc
        if check and result.returncode != 0:
            message = (result.stderr + result.stdout).decode("utf-8", errors="replace").strip()
            raise GitError(message or f"Git command failed: git {' '.join(args)}")
        return result

    @classmethod
    def discover(cls, start_path: Path | None = None) -> GitRepository:
        result = cls._run(["rev-parse", "--show-toplevel"], cwd=start_path, check=False)
        if result.returncode != 0:
            raise GitError("Current directory is not inside a Git repository.")
        root = Path(os.fsdecode(result.stdout.rstrip(b"\n"))).resolve()
        head = cls._run(["rev-parse", "--verify", "HEAD"], cwd=root, check=False)
        if head.returncode != 0:
            raise GitError("This repository has no commits yet; create an initial commit before using Commitron.")
        return cls(root)

    def _index_env(self, index_path: str) -> dict[str, str]:
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = index_path
        return env

    @staticmethod
    def _literal(path: str) -> str:
        return f":(literal){path}"

    def _new_index(self) -> str:
        descriptor, path = tempfile.mkstemp(prefix="commitron-index-")
        os.close(descriptor)
        return path

    def _head(self) -> str:
        return self._run(["rev-parse", "HEAD"], cwd=self.root).stdout.decode("ascii").strip()

    def _ensure_safe_state(self) -> None:
        for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD", "BISECT_LOG"):
            path = self._run(["rev-parse", "--git-path", marker], cwd=self.root).stdout.decode().strip()
            if (self.root / path).exists():
                raise GitError(f"A Git {marker.removesuffix('_HEAD').lower()} operation is in progress; finish it first.")
        for marker in ("rebase-apply", "rebase-merge"):
            path = self._run(["rev-parse", "--git-path", marker], cwd=self.root).stdout.decode().strip()
            if (self.root / path).exists():
                raise GitError("A Git rebase is in progress; finish it first.")
        unmerged = self._run(["ls-files", "-u", "-z"], cwd=self.root).stdout
        if unmerged:
            raise GitError("The index has unresolved conflicts; resolve them before using Commitron.")

    def snapshot(self) -> Snapshot:
        self._ensure_safe_state()
        base_head = self._head()
        index_signature = self._run(["ls-files", "--stage", "-z"], cwd=self.root).stdout
        tracked_diff = self._run(
            ["diff", "--binary", "--no-ext-diff", "--no-renames", "HEAD", "--"], cwd=self.root
        ).stdout
        untracked_result = self._run(
            ["ls-files", "--others", "--exclude-standard", "-z"], cwd=self.root
        )
        untracked = [os.fsdecode(path) for path in untracked_result.stdout.split(b"\0") if path]
        index_path = self._new_index()
        env = self._index_env(index_path)
        try:
            self._run(["read-tree", "HEAD"], cwd=self.root, env=env)
            if tracked_diff:
                self._run(["apply", "--cached", "--binary", "-"], cwd=self.root, env=env, input_data=tracked_diff)
            if untracked:
                self._run(
                    ["add", "-A", "--", *(self._literal(path) for path in untracked)],
                    cwd=self.root,
                    env=env,
                )
            diff = self._run(
                ["diff", "--cached", "--binary", "--no-ext-diff", "--no-renames", "HEAD", "--"],
                cwd=self.root,
                env=env,
            ).stdout
            path_output = self._run(
                ["diff", "--cached", "--name-only", "-z", "--no-renames", "HEAD", "--"],
                cwd=self.root,
                env=env,
            ).stdout
            files = [os.fsdecode(path) for path in path_output.split(b"\0") if path]
            return Snapshot(
                diff.decode("utf-8", errors="replace"),
                len(diff),
                files,
                index_path,
                base_head,
                index_signature,
            )
        except Exception:
            try:
                os.unlink(index_path)
            except FileNotFoundError:
                pass
            raise

    def _snapshot_entries(self, index_path: str) -> dict[str, tuple[str, str]]:
        output = self._run(["ls-files", "--stage", "-z"], cwd=self.root, env=self._index_env(index_path)).stdout
        entries: dict[str, tuple[str, str]] = {}
        for record in output.split(b"\0"):
            if not record:
                continue
            metadata, raw_path = record.split(b"\t", 1)
            mode, oid, stage = metadata.decode("ascii").split(" ")
            if stage == "0":
                entries[os.fsdecode(raw_path)] = (mode, oid)
        return entries

    def _indexed_paths(self, index_path: str) -> set[str]:
        output = self._run(["ls-files", "-z"], cwd=self.root, env=self._index_env(index_path)).stdout
        return {os.fsdecode(path) for path in output.split(b"\0") if path}

    def create_commits(self, snapshot: Snapshot, commits: list[PlannedCommit]) -> list[str]:
        if self._head() != snapshot.base_head:
            raise GitError("HEAD changed after the diff was captured; run Commitron again to review the new state.")
        snapshot_entries = self._snapshot_entries(snapshot.index_path)
        commit_index = self._new_index()
        env = self._index_env(commit_index)
        hashes: list[str] = []
        try:
            for number, commit in enumerate(commits, start=1):
                try:
                    self._run(["read-tree", "HEAD"], cwd=self.root, env=env)
                    existing = self._indexed_paths(commit_index)
                    for path in commit.files:
                        literal = self._literal(path)
                        if path in existing:
                            # update-index --force-remove does not honor pathspec magic; git rm does.
                            self._run(["rm", "--cached", "--force", "--", literal], cwd=self.root, env=env)
                        entry = snapshot_entries.get(path)
                        if entry:
                            mode, oid = entry
                            # Three-argument cacheinfo keeps commas and unusual characters in paths safe.
                            self._run(
                                ["update-index", "--add", "--cacheinfo", mode, oid, path],
                                cwd=self.root,
                                env=env,
                            )
                    args = ["commit", "-m", commit.title]
                    if commit.description:
                        args.extend(["-m", commit.description])
                    self._run(args, cwd=self.root, env=env)
                    short_hash = self._run(["rev-parse", "--short", "HEAD"], cwd=self.root).stdout.decode().strip()
                    hashes.append(short_hash)
                except GitError as exc:
                    if hashes:
                        created = ", ".join(hashes)
                        raise GitError(
                            f"Commit {number} failed after {len(hashes)} commit(s) were created "
                            f"({created}). Remaining changes were not committed. {exc}"
                        ) from exc
                    raise
            return hashes
        finally:
            # The original index may describe the old HEAD now; reset it to the final HEAD.
            # Any later worktree edits remain visible as unstaged changes.
            if hashes:
                try:
                    current_signature = self._run(["ls-files", "--stage", "-z"], cwd=self.root).stdout
                    if current_signature == snapshot.real_index_signature:
                        self._run(["read-tree", "HEAD"], cwd=self.root)
                    else:
                        self.real_index_preserved = True
                except GitError:
                    # Keep what is in the real index rather than risk overwriting user data.
                    self.real_index_preserved = True
            try:
                os.unlink(commit_index)
            except FileNotFoundError:
                pass
