"""Synthetic temporary-repository regressions for sync write closure."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import catalog_impact as ci


class SyncSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.bundle = self.repo / ".agents/knowledge"
        self.bundle.mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "--allow-empty", "-m", "Synthetic fixture baseline"], cwd=self.repo, check=True)
        self.concept = self.bundle / "concept.md"
        self.concept.write_text("---\ntimestamp: old\n---\n\nKeep body.\n")
        self.log = self.bundle / "log.md"
        self.log.write_text("# Log\n")
        self.catalog = self.bundle / "catalog-scopes.yaml"
        self.catalog.write_text("version: 1\ntracked_roots: [source.txt]\nignored_paths: []\nscopes:\n  core:\n    concept: concept.md\n    paths: [source.txt]\n")
        (self.repo / "source.txt").write_text("fixture source")

    def tearDown(self):
        self.temp.cleanup()

    def run_sync(self, *extra):
        return subprocess.run([sys.executable, str(Path(ci.__file__)), "--repo-root", str(self.repo), "--bundle", str(self.bundle), "sync", "--worktree", "--scope", "core", *extra], capture_output=True, text=True)

    def test_empty_ignored_paths_is_valid(self):
        self.assertEqual(ci.load_catalog(self.catalog).ignored_paths, ())

    def test_traversal_and_absolute_catalog_concept_refused(self):
        for relative in ["../../outside.md", str(self.root / "outside.md"), "C:/outside.md"]:
            self.catalog.write_text(f"version: 1\nscopes:\n  core:\n    concept: {relative}\n    paths: [source.txt]\n")
            result = self.run_sync("--write")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.log.read_text(), "# Log\n")

    def test_symlink_concept_and_log_refused_without_writing_target(self):
        outside = self.root / "outside.md"
        outside.write_text("---\ntimestamp: keep\n---\nprivate fixture\n")
        for target in [self.concept, self.log]:
            original = target.read_text()
            target.unlink()
            target.symlink_to(outside)
            try:
                self.assertNotEqual(self.run_sync("--write").returncode, 0)
                self.assertIn("timestamp: keep", outside.read_text())
            finally:
                target.unlink()
                target.write_text(original)

    def test_bundle_outside_repo_or_linked_bundle_refused(self):
        with self.assertRaises(ValueError):
            ci.contained_target(self.repo, self.root)
        alias = self.repo / "linked"
        alias.symlink_to(self.bundle, target_is_directory=True)
        with self.assertRaises(ValueError):
            ci.contained_target(self.repo, alias, "concept.md")

    def test_missing_log_fails_before_any_concept_write(self):
        before = self.concept.read_bytes()
        self.log.unlink()
        self.assertNotEqual(self.run_sync("--write").returncode, 0)
        self.assertEqual(self.concept.read_bytes(), before)
        self.assertFalse(self.log.exists())

    def test_preview_is_read_only_and_successful_sync_is_idempotent(self):
        before = {p: p.read_bytes() for p in [self.concept, self.log]}
        preview = self.run_sync()
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        applied = self.run_sync("--write")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertIn("Keep body.", self.concept.read_text())
        self.assertIn("source_fingerprint:", self.concept.read_text())
        second = self.run_sync("--write")
        self.assertEqual(second.returncode, 0)
        self.assertIn("changed_files=0", second.stdout)

    def test_preflight_staging_failure_preserves_every_file(self):
        before = self.concept.read_bytes()
        with self.assertRaises(ValueError):
            ci.apply_updates(self.repo, self.bundle, {self.concept: "changed", self.bundle / "missing.md": "bad"})
        self.assertEqual(self.concept.read_bytes(), before)
        self.assertEqual(list(self.bundle.glob(".okf-*")), [])

    def test_replacement_failure_rolls_back_and_never_reports_success(self):
        before = {p: p.read_bytes() for p in [self.concept, self.log]}
        original = Path.replace
        count = [0]
        def fail_second(path, target):
            count[0] += 1
            if count[0] == 2:
                raise OSError("fixture replacement failure")
            return original(path, target)
        with patch.object(Path, "replace", fail_second):
            with self.assertRaisesRegex(ValueError, "restored"):
                ci.apply_updates(self.repo, self.bundle, {self.concept: "changed", self.log: "changed log"})
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_external_source_link_is_not_read_for_fingerprint(self):
        outside = self.root / "outside.txt"
        outside.write_text("fixture content")
        source = self.repo / "source.txt"
        source.unlink()
        source.symlink_to(outside)
        self.assertNotEqual(self.run_sync("--write").returncode, 0)
        self.assertNotIn("source_fingerprint:", self.concept.read_text())
