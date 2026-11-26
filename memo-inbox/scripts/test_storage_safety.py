"""Synthetic storage-boundary regressions; never use a configured real vault."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import memo_inbox as mi

SCRIPT = Path(mi.__file__)
AT = "2026-01-01T00:00:00+00:00"


class StorageSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.config = self.root / "config"
        self.config.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, **kw):
        args = dict(original="synthetic memo", source="fixture", reported_at=AT, config_dir=self.config)
        args.update(kw)
        return mi.write_memo(self.vault, **args)

    def test_git_directory_and_worktree_git_file_refused(self):
        for name, directory in [("repo", True), ("worktree", False)]:
            root = self.root / name
            root.mkdir()
            marker = root / ".git"
            marker.mkdir() if directory else marker.write_text("gitdir: unused")
            with self.assertRaises(mi.ItemError):
                mi.safe_dest(root, "memo.md")
            self.assertFalse((root / "memo.md").exists())

    def test_renamed_runtime_distribution_without_markers_refused(self):
        pack = self.root / "renamed-pack"
        scripts = pack / "renamed-skill" / "scripts"
        scripts.mkdir(parents=True)
        copied = scripts / "memo_inbox.py"
        shutil.copyfile(SCRIPT, copied)
        # The running helper protects its own package root regardless of names.
        result = subprocess.run([sys.executable, str(copied), "write-memo", "--vault-root", str(pack), "--config-dir", str(self.config), "--original", "fixture", "--source", "test", "--reported-at", AT], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((pack / "备忘").exists())

    def test_config_repository_refused_before_note_or_index_read(self):
        (self.config / ".git").write_text("gitdir: unused")
        with patch.object(mi, "load_memo_index", side_effect=AssertionError("must not read")):
            with self.assertRaises(mi.ItemError):
                self.write()
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_missing_vault_does_not_create_replacement_or_config(self):
        missing = self.root / "missing-mount" / "vault"
        config = self.root / "new-config"
        with self.assertRaises(mi.ItemError):
            mi.write_memo(missing, original="fixture", source="test", reported_at=AT, config_dir=config)
        self.assertFalse(missing.parent.exists())
        self.assertFalse(config.exists())

    def test_changed_mount_identity_is_not_silently_rebound(self):
        self.write()
        self.vault.rename(self.root / "detached-vault")
        self.vault.mkdir()
        with self.assertRaisesRegex(mi.ItemError, "identity changed"):
            self.write(original="second fixture")
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_sanitized_title_duplicate_still_matches(self):
        first = self.write(original="fixture: example")
        second = self.write(original="fixture: example")
        self.assertEqual(second["action"], "duplicate")
        self.assertEqual(first["path"], second["path"])

    def test_empty_unrelated_indexed_file_is_not_duplicate(self):
        self.write()
        wrong = self.vault / "unrelated.md"
        wrong.write_text("")
        index = mi.load_memo_index(self.config)
        index["items"][0]["relpath"] = "unrelated.md"
        mi.save_memo_index(index, self.config)
        with self.assertRaises(mi.ItemError):
            self.write()

    def test_symlink_root_destination_index_and_config_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        for slot, target in [(self.root / "linked-vault", self.vault), (self.vault / "备忘", outside), (self.root / "linked-config", self.config)]:
            slot.symlink_to(target, target_is_directory=True)
        for root, rel in [(self.root / "linked-vault", "memo.md"), (self.vault, "备忘/memo.md")]:
            with self.assertRaises(mi.ItemError):
                mi.safe_dest(root, rel)
        with self.assertRaises(mi.ItemError):
            self.write(config_dir=self.root / "linked-config")
        (self.config / "memo-index.json").symlink_to(outside / "index.json")
        with self.assertRaises(mi.ItemError):
            self.write()
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "Windows junction regression requires Windows")
    def test_windows_junction_refused(self):
        junction = self.root / "junction"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(self.vault)], check=True, capture_output=True)
        try:
            with self.assertRaises(mi.ItemError):
                mi.require_vault(junction)
        finally:
            os.rmdir(junction)

    def test_index_escape_refused_before_reading_outside_file(self):
        for rel in ["../outside.md", str(self.root / "outside.md")]:
            mi.save_memo_index({"items": [{"id": "fixture", "idempotency_key": mi.idempotency_key("synthetic memo", "fixture"), "relpath": rel}]}, self.config)
            with self.assertRaises(mi.ItemError):
                self.write()
        self.assertFalse((self.vault / "备忘").exists())

    def test_legacy_create_and_existing_item_update_cannot_write_repository(self):
        repo = self.root / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        target = repo / "existing.md"
        target.write_text("unchanged")
        with self.assertRaises(mi.ItemError):
            mi.write_item_file(target, "changed")
        with self.assertRaises(mi.ItemError):
            mi.create_item(repo, "fixture", "test", AT)
        self.assertEqual(target.read_text(), "unchanged")

    def test_concurrent_cli_writes_preserve_all_index_entries(self):
        def one(i):
            return subprocess.run([sys.executable, str(SCRIPT), "write-memo", "--vault-root", str(self.vault), "--config-dir", str(self.config), "--original", f"fixture number {i}", "--source", "test", "--reported-at", AT], capture_output=True, text=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(one, range(10)))
        self.assertTrue(all(p.returncode == 0 for p in results), [(p.returncode, p.stdout, p.stderr) for p in results])
        self.assertEqual(len(mi.load_memo_index(self.config)["items"]), 10)
        self.assertEqual(len(list((self.vault / "备忘").glob("*.md"))), 10)

    def test_concurrent_different_bodies_same_title_do_not_overwrite(self):
        def one(i):
            try:
                return self.write(original=f"fixture body {i}", title="shared")
            except mi.ItemError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(one, range(6)))
        self.assertEqual(sum(r is not None for r in results), 1)
        note = self.vault / "备忘/shared.md"
        self.assertIn(note.read_text().strip(), [f"fixture body {i}" for i in range(6)])
        self.assertEqual(len(mi.load_memo_index(self.config)["items"]), 1)

    def test_io_failure_returns_failure_not_saved_success(self):
        with patch.object(mi, "save_memo_index", side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):
                self.write()
        # Honest partial state: note exists but the index was not persisted.
        self.assertEqual(len(list((self.vault / "备忘").glob("*.md"))), 1)
        self.assertFalse((self.config / "memo-index.json").exists())
