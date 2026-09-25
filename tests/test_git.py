from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from commitron.git import CommitPlan, GitError, GitRepository, PlannedCommit


def git(path: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=path, text=True, capture_output=True, check=check
    )
    return result.stdout.strip()


class GitWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Test User")
        git(self.root, "config", "user.email", "test@example.com")
        (self.root / "one.txt").write_text("initial one\n")
        (self.root / "two.txt").write_text("initial two\n")
        (self.root / "comma,name.txt").write_text("initial comma\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "initial")
        self.repo = GitRepository.discover(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_snapshot_and_two_commits_include_untracked_file(self) -> None:
        (self.root / "one.txt").write_text("updated one\n")
        (self.root / "two.txt").write_text("updated two\n")
        (self.root / "comma,name.txt").write_text("updated comma\n")
        (self.root / "new file.txt").write_text("new content\n")
        snapshot = self.repo.snapshot()
        try:
            self.assertEqual(
                set(snapshot.files), {"one.txt", "two.txt", "comma,name.txt", "new file.txt"}
            )
            commits = [
                PlannedCommit(["one.txt", "new file.txt"], "Add new file and update one"),
                PlannedCommit(["two.txt", "comma,name.txt"], "Update remaining files"),
            ]
            hashes = self.repo.create_commits(snapshot, commits)
            self.assertEqual(len(hashes), 2)
            self.assertEqual(git(self.root, "log", "-2", "--pretty=%s"), "Update remaining files\nAdd new file and update one")
            self.assertEqual(git(self.root, "status", "--porcelain"), "")
        finally:
            snapshot.close()

    def test_dry_snapshot_does_not_change_real_index(self) -> None:
        (self.root / "one.txt").write_text("edited\n")
        git(self.root, "add", "one.txt")
        before = git(self.root, "status", "--porcelain")
        snapshot = self.repo.snapshot()
        try:
            self.assertEqual(set(snapshot.files), {"one.txt"})
            self.assertEqual(git(self.root, "status", "--porcelain"), before)
        finally:
            snapshot.close()

    def test_staged_snapshot_is_committed_even_if_worktree_is_later_edited(self) -> None:
        (self.root / "one.txt").write_text("reviewed version\n")
        git(self.root, "add", "one.txt")
        snapshot = self.repo.snapshot()
        try:
            (self.root / "one.txt").write_text("later unreviewed edit\n")
            plan = [PlannedCommit(["one.txt"], "Update one")]
            self.repo.create_commits(snapshot, plan)
            self.assertEqual((self.root / "one.txt").read_text(), "later unreviewed edit\n")
            self.assertIn("reviewed version", git(self.root, "show", "HEAD:one.txt"))
            self.assertIn("one.txt", git(self.root, "status", "--porcelain"))
        finally:
            snapshot.close()

    def test_concurrent_staging_is_not_overwritten(self) -> None:
        (self.root / "one.txt").write_text("snapshot for commit\n")
        snapshot = self.repo.snapshot()
        try:
            (self.root / "two.txt").write_text("staged concurrently\n")
            git(self.root, "add", "two.txt")
            self.repo.create_commits(snapshot, [PlannedCommit(["one.txt"], "Update one")])
            self.assertTrue(self.repo.real_index_preserved)
            staged = git(self.root, "diff", "--cached", "--name-only")
            self.assertIn("two.txt", staged)
        finally:
            snapshot.close()

    def test_refuses_to_run_during_merge(self) -> None:
        git_dir = Path(git(self.root, "rev-parse", "--git-dir"))
        if not git_dir.is_absolute():
            git_dir = self.root / git_dir
        (git_dir / "MERGE_HEAD").write_text("placeholder\n")
        with self.assertRaises(GitError):
            self.repo.snapshot()

    def test_reports_partial_success_if_later_commit_hook_fails(self) -> None:
        (self.root / "one.txt").write_text("first change\n")
        (self.root / "two.txt").write_text("second change\n")
        snapshot = self.repo.snapshot()
        marker = self.root / "hook-ran"
        hook = self.root / ".git" / "hooks" / "pre-commit"
        hook.write_text(f"#!/bin/sh\nif test -e '{marker}'; then exit 1; fi\ntouch '{marker}'\n")
        hook.chmod(0o755)
        try:
            with self.assertRaisesRegex(GitError, r"1 commit\(s\) were created"):
                self.repo.create_commits(
                    snapshot,
                    [PlannedCommit(["one.txt"], "First update"), PlannedCommit(["two.txt"], "Second update")],
                )
            self.assertEqual(git(self.root, "rev-list", "--count", "HEAD"), "2")
            self.assertIn("two.txt", git(self.root, "status", "--porcelain"))
        finally:
            snapshot.close()

    def test_deletion_is_committed(self) -> None:
        (self.root / "two.txt").unlink()
        snapshot = self.repo.snapshot()
        try:
            self.assertEqual(snapshot.files, ["two.txt"])
            self.repo.create_commits(snapshot, [PlannedCommit(["two.txt"], "Remove obsolete file")])
            result = subprocess.run(
                ["git", "cat-file", "-e", "HEAD:two.txt"],
                cwd=self.root,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
        finally:
            snapshot.close()


class PlanValidationTests(unittest.TestCase):
    def test_requires_exactly_once_coverage(self) -> None:
        value = {
            "commits": [
                {"files": ["one", "three"], "title": "Change first group"},
                {"files": ["two"], "title": "Change second group"},
            ]
        }
        plan = CommitPlan.from_json(value, ["one", "two", "three"], False)
        self.assertEqual(len(plan.commits), 2)

    def test_rejects_duplicate_unknown_and_omitted_paths(self) -> None:
        invalid_plans = [
            {"commits": [{"files": ["one", "one"], "title": "Duplicate"}]},
            {"commits": [{"files": ["unknown"], "title": "Unknown"}]},
            {"commits": [{"files": ["one"], "title": "Omitted"}]},
        ]
        for value in invalid_plans:
            with self.subTest(value=value), self.assertRaises(GitError):
                CommitPlan.from_json(value, ["one", "two"], False)

    def test_title_must_be_single_line(self) -> None:
        value = {"commits": [{"files": ["one"], "title": "Bad\nTitle"}]}
        with self.assertRaises(GitError):
            CommitPlan.from_json(value, ["one"], False)


if __name__ == "__main__":
    unittest.main()
