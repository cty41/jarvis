"""Deterministic tests for memo-inbox helpers.

Fixtures stay under this tests/scripts tree. This pack does not ship
historical inbox items.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import memo_inbox as mi  # noqa: E402

SCRIPT = SCRIPT_DIR / "memo_inbox.py"
EXAMPLE_TEXT = "周六去图书馆还书"
EXAMPLE_SOURCE = "user-chat"
EXAMPLE_AT = "2026-11-13T18:00:00+08:00"
EXAMPLE_LATER = "2026-11-13T19:30:00+08:00"


def run(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def load_stdout(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


class HelperTests(unittest.TestCase):
    def test_key_and_id_are_deterministic(self) -> None:
        key = mi.idempotency_key(EXAMPLE_TEXT, EXAMPLE_SOURCE)
        self.assertEqual(key, mi.idempotency_key("  周六去图书馆还书  ", "user-chat"))
        self.assertEqual(mi.make_id(EXAMPLE_AT, key), f"20261113-{key[:8]}")
        self.assertNotEqual(key, mi.idempotency_key(EXAMPLE_TEXT, "another-source"))

    def test_normalize_ignores_line_endings_and_trailing_spaces(self) -> None:
        self.assertEqual(
            mi.normalize_text("周六去图书馆还书  \r\n第二行  "),
            "周六去图书馆还书\n第二行",
        )

    def test_timestamp_requires_offset(self) -> None:
        with self.assertRaises(mi.ItemError):
            mi.parse_instant("2026-11-13T18:00:00")


class CreateAndDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.inbox = Path(self.tmp.name) / "inbox"
        self.inbox.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def create(self, original: str = EXAMPLE_TEXT, source: str = EXAMPLE_SOURCE, **kwargs: str) -> dict:
        result = mi.create_item(
            self.inbox,
            original=original,
            source=source,
            reported_at=kwargs.get("reported_at", EXAMPLE_AT),
            occurred_at=kwargs.get("occurred_at", ""),
        )
        return result

    def test_create_writes_one_file_named_after_id(self) -> None:
        result = self.create()
        item = result["item"]
        self.assertEqual(result["action"], "created")
        self.assertEqual(item["fields"]["status"], "pending")
        self.assertEqual(item["original"], EXAMPLE_TEXT)
        self.assertEqual(item["fields"]["occurred_at"], "")
        path = Path(item["path"])
        self.assertEqual(path.name, f"{item['fields']['id']}.md")
        self.assertEqual(path.parent, self.inbox / "items")
        self.assertTrue(path.is_file())
        self.assertEqual(len(list((self.inbox / "items").glob("*.md"))), 1)

    def test_duplicate_message_reuses_the_same_id(self) -> None:
        first = self.create()
        second = self.create(original="  周六去图书馆还书\n")
        self.assertEqual(second["action"], "duplicate")
        self.assertEqual(first["item"]["fields"]["id"], second["item"]["fields"]["id"])
        self.assertEqual(len(list((self.inbox / "items").glob("*.md"))), 1)

    def test_same_id_different_text_is_needs_review(self) -> None:
        first = self.create()
        target_id = first["item"]["fields"]["id"]
        other_text = "周日去超市买牛奶"
        original_make_id = mi.make_id
        mi.make_id = lambda reported_at, key: target_id
        try:
            result = mi.create_item(
                self.inbox,
                original=other_text,
                source="other-source",
                reported_at=EXAMPLE_AT,
            )
        finally:
            mi.make_id = original_make_id
        self.assertEqual(result["action"], "conflict")
        self.assertEqual(result["item"]["fields"]["status"], "needs-review")
        self.assertEqual(result["item"]["original"], EXAMPLE_TEXT)
        self.assertIn(other_text, result["item"]["conflicts"])
        self.assertIn("other-source", result["item"]["conflicts"])
        self.assertEqual(
            result["item"]["fields"]["idempotency_key"],
            first["item"]["fields"]["idempotency_key"],
        )
        self.assertEqual(len(list((self.inbox / "items").glob("*.md"))), 1)

    def test_occurred_at_is_stored_when_known(self) -> None:
        result = self.create(occurred_at="2026-11-14T10:00:00+08:00")
        self.assertEqual(result["item"]["fields"]["occurred_at"], "2026-11-14T10:00:00+08:00")


class CorrectionAndStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.inbox = Path(self.tmp.name) / "inbox"
        self.inbox.mkdir()
        created = mi.create_item(
            self.inbox,
            original=EXAMPLE_TEXT,
            source=EXAMPLE_SOURCE,
            reported_at=EXAMPLE_AT,
        )
        self.path = Path(created["item"]["path"])
        self.original = created["item"]["original"]
        self.fields = dict(created["item"]["fields"])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_append_correction_does_not_change_original(self) -> None:
        result = mi.append_correction(self.path, "改到周日还书", EXAMPLE_LATER)
        self.assertEqual(result["item"]["original"], self.original)
        self.assertEqual(result["item"]["fields"], self.fields)
        self.assertIn("改到周日还书", result["item"]["corrections"])
        self.assertIn(EXAMPLE_LATER, result["item"]["corrections"])

    def test_there_is_no_api_to_rewrite_original(self) -> None:
        self.assertFalse(hasattr(mi, "rewrite_original"))
        self.assertFalse(hasattr(mi, "update_original"))

    def test_status_transitions(self) -> None:
        mi.set_status(self.path, "prepared")
        self.assertEqual(mi.read_item(self.path)["fields"]["status"], "prepared")
        with self.assertRaises(mi.ItemError):
            # imported from prepared still requires imported_path
            mi.set_status(self.path, "imported")
        mi.set_status(
            self.path,
            "imported",
            imported_path="inbox/20261113-demo.md",
            imported_at=EXAMPLE_LATER,
        )
        imported = mi.read_item(self.path)
        self.assertEqual(imported["fields"]["status"], "imported")
        self.assertEqual(imported["fields"]["imported_path"], "inbox/20261113-demo.md")
        # Retrying the same status does not fail and does not require a rewrite.
        again = mi.set_status(self.path, "imported")
        self.assertEqual(again["item"]["fields"]["imported_path"], "inbox/20261113-demo.md")
        with self.assertRaises(mi.ItemError):
            mi.set_status(self.path, "pending")
        mi.set_status(self.path, "needs-review")
        self.assertEqual(mi.read_item(self.path)["fields"]["status"], "needs-review")

    def test_validate_rejects_filename_mismatch(self) -> None:
        item = mi.read_item(self.path)
        wrong = self.path.with_name("19990101-deadbeef.md")
        wrong.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(mi.ItemError):
            mi.read_item(wrong)
        errors = mi.validate_inbox(self.inbox)
        self.assertTrue(any("does not match id" in row["error"] for row in errors))
        self.assertEqual(item["original"], EXAMPLE_TEXT)


class ConfigAndVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = self.root / "config"
        self.config.mkdir()
        self.vault = self.root / "default-vault"
        self.vault.mkdir()
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()
        created = mi.create_item(
            self.inbox,
            original=EXAMPLE_TEXT,
            source=EXAMPLE_SOURCE,
            reported_at=EXAMPLE_AT,
        )
        self.item_path = Path(created["item"]["path"])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_resolve_vaults_reads_config_and_leaves_missing_null(self) -> None:
        (self.config / "default-vault.json").write_text(
            json.dumps({"vaultPath": str(self.vault)}),
            encoding="utf-8",
        )
        resolved = mi.resolve_vaults(self.config)
        self.assertEqual(resolved["default_vault_path"], str(self.vault))
        self.assertIsNone(resolved["sensitive_vault_path"])

    def test_resolve_vaults_rejects_invalid_json(self) -> None:
        (self.config / "records-vault.json").write_text("{", encoding="utf-8")
        with self.assertRaises(mi.ItemError):
            mi.resolve_vaults(self.config)

    def test_write_vault_note_and_readback(self) -> None:
        dest = mi.safe_dest(self.vault, "inbox/library-memo.md")
        body = mi.render_vault_note(mi.read_item(self.item_path))
        result = mi.write_vault_note(dest, body)
        self.assertEqual(result["action"], "written")
        text = Path(result["path"]).read_text(encoding="utf-8")
        self.assertIn(EXAMPLE_TEXT, text)
        self.assertIn("idempotency_key:", text)
        again = mi.write_vault_note(dest, body)
        self.assertEqual(again["action"], "already-present")

    def test_write_vault_note_refuses_different_content(self) -> None:
        dest = mi.safe_dest(self.vault, "inbox/library-memo.md")
        mi.write_vault_note(dest, "first\n")
        with self.assertRaises(mi.ItemError) as ctx:
            mi.write_vault_note(dest, "second\n")
        self.assertIn("already exists with different content", str(ctx.exception))

    def test_refuses_to_write_into_skill_pack_checkout(self) -> None:
        with self.assertRaises(mi.ItemError) as ctx:
            mi.safe_dest(REPO_ROOT, "notes/should-not-write.md")
        self.assertIn("skill-pack checkout", str(ctx.exception))
        # A vault must also be rejected if it lives inside this checkout,
        # including layouts that have no historical inbox/ directory.
        with self.assertRaises(mi.ItemError):
            mi.safe_dest(REPO_ROOT / "memo-inbox", "should-not-write.md")

    def test_refuses_checkout_without_inbox_and_copied_or_linked_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "jarvis-copy"
            skill = pack / "memo-inbox"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("# memo-inbox\n", encoding="utf-8")
            with self.assertRaises(mi.ItemError) as ctx:
                mi.safe_dest(pack, "备忘/should-not-write.md")
            self.assertIn("skill-pack checkout", str(ctx.exception))

            linked = Path(tmp) / "linked-pack"
            linked.mkdir()
            (linked / "memo-inbox").symlink_to(skill, target_is_directory=True)
            with self.assertRaises(mi.ItemError):
                mi.safe_dest(linked, "备忘/should-not-write.md")

            ordinary = Path(tmp) / "ordinary-vault"
            ordinary.mkdir()
            dest = mi.safe_dest(ordinary, "备忘/ok.md")
            self.assertEqual(dest, (ordinary / "备忘/ok.md").resolve())

    def test_refuses_parent_or_absolute_destination(self) -> None:
        with self.assertRaises(mi.ItemError):
            mi.safe_dest(self.vault, "../escape.md")
        with self.assertRaises(mi.ItemError):
            mi.safe_dest(self.vault, str(self.root / "outside.md"))

    def test_status_retry_does_not_require_rewriting_the_note(self) -> None:
        dest_rel = f"inbox/{mi.read_item(self.item_path)['fields']['id']}.md"
        dest = mi.safe_dest(self.vault, dest_rel)
        written = mi.write_vault_note(dest, mi.render_vault_note(mi.read_item(self.item_path)))
        first = mi.set_status(
            self.item_path,
            "imported",
            imported_path=dest_rel,
            imported_at=EXAMPLE_LATER,
        )
        before = Path(written["path"]).read_text(encoding="utf-8")
        # Simulate a failed remote status writeback by only retrying set-status.
        second = mi.set_status(self.item_path, "imported")
        after = Path(written["path"]).read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertEqual(first["item"]["fields"]["imported_path"], dest_rel)
        self.assertEqual(second["item"]["fields"]["imported_path"], dest_rel)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.config = self.root / "config"
        self.config.mkdir()
        (self.config / "default-vault.json").write_text(
            json.dumps({"vaultPath": str(self.vault)}),
            encoding="utf-8",
        )
        (self.config / "records-vault.json").write_text(
            json.dumps({"vaultPath": str(self.root / "sensitive")}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cli_create_validate_show_and_same_entry(self) -> None:
        created = run(
            "create",
            "--inbox-root",
            str(self.inbox),
            "--original",
            EXAMPLE_TEXT,
            "--source",
            EXAMPLE_SOURCE,
            "--reported-at",
            EXAMPLE_AT,
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        payload = load_stdout(created)
        self.assertEqual(payload["action"], "created")
        path = payload["path"]
        again = run(
            "create",
            "--inbox-root",
            str(self.inbox),
            "--original",
            EXAMPLE_TEXT,
            "--source",
            EXAMPLE_SOURCE,
            "--reported-at",
            EXAMPLE_AT,
        )
        self.assertEqual(again.returncode, 0)
        self.assertEqual(load_stdout(again)["action"], "duplicate")
        self.assertEqual(load_stdout(again)["id"], payload["id"])

        validated = run("validate", "--item", path)
        self.assertEqual(validated.returncode, 0, validated.stderr)
        shown = run("show", "--item", path)
        self.assertEqual(load_stdout(shown)["original"], EXAMPLE_TEXT)

        inbox_validated = run("validate", "--inbox-root", str(self.inbox))
        self.assertEqual(inbox_validated.returncode, 0)

        same = run("same-entry", "--a", path, "--b", path)
        self.assertEqual(same.returncode, 0)
        self.assertTrue(load_stdout(same)["same_entry"])

        run(
            "append-correction",
            "--item",
            path,
            "--text",
            "改到周日还书",
            "--at",
            EXAMPLE_LATER,
            check=True,
        )
        after = load_stdout(run("show", "--item", path))
        self.assertEqual(after["original"], EXAMPLE_TEXT)
        self.assertIn("改到周日还书", after["corrections"])

        written = run(
            "write-vault-note",
            "--vault-root",
            str(self.vault),
            "--dest-relpath",
            "inbox/library-memo.md",
            "--item",
            path,
        )
        self.assertEqual(written.returncode, 0, written.stderr)
        self.assertEqual(load_stdout(written)["action"], "written")

        status = run(
            "set-status",
            "--item",
            path,
            "--status",
            "imported",
            "--imported-path",
            "inbox/library-memo.md",
            "--imported-at",
            EXAMPLE_LATER,
        )
        self.assertEqual(status.returncode, 0, status.stderr)

        vaults = run("resolve-vaults", "--config-dir", str(self.config))
        self.assertEqual(vaults.returncode, 0, vaults.stderr)
        resolved = load_stdout(vaults)
        self.assertEqual(resolved["default_vault_path"], str(self.vault))
        self.assertTrue(resolved["sensitive_vault_path"].endswith("sensitive"))

        refused = run(
            "write-vault-note",
            "--vault-root",
            str(REPO_ROOT),
            "--dest-relpath",
            "inbox/nope.md",
            "--item",
            path,
        )
        self.assertEqual(refused.returncode, mi.EXIT_REFUSED)
        self.assertIn("skill-pack checkout", load_stdout(refused)["error"])

    def test_cli_rejects_empty_original(self) -> None:
        result = run(
            "create",
            "--inbox-root",
            str(self.inbox),
            "--original",
            "   ",
            "--source",
            EXAMPLE_SOURCE,
            "--reported-at",
            EXAMPLE_AT,
        )
        self.assertEqual(result.returncode, mi.EXIT_USAGE)
        self.assertFalse(load_stdout(result)["ok"])


class TitleAndFilenameTests(unittest.TestCase):
    def test_short_memo_uses_stripped_text_as_title_without_body(self) -> None:
        title, body = mi.memo_title_and_body("记一下 周六去图书馆还书")
        self.assertEqual(title, "周六去图书馆还书")
        self.assertEqual(body, "")
        title, body = mi.memo_title_and_body("记一下，回去把雨伞放到门口")
        self.assertEqual(title, "回去把雨伞放到门口")
        self.assertEqual(body, "")

    def test_long_memo_keeps_original_body_and_a_faithful_short_title(self) -> None:
        original = "记一下 周末要去图书馆还书。另外把过期的会员卡续上，顺便看看展览。"
        title, body = mi.memo_title_and_body(original)
        self.assertEqual(title, "周末要去图书馆还书")
        self.assertEqual(body, "周末要去图书馆还书。另外把过期的会员卡续上，顺便看看展览。")
        self.assertNotIn("展览门票涨价", title)
        self.assertNotIn("记一下", body)

    def test_long_single_sentence_is_summarized(self) -> None:
        original = "再记一下 周末计划 把书房整理扩成类似旧书店里一边查目录  一边做笔记的半天安排"
        title, body = mi.memo_title_and_body(original)
        stripped = "周末计划 把书房整理扩成类似旧书店里一边查目录  一边做笔记的半天安排"
        self.assertEqual(body, stripped)
        self.assertLessEqual(len(title), mi.SOFT_TITLE_LIMIT)
        self.assertNotEqual(title, stripped)
        for token in title.replace("：", " ").split():
            self.assertIn(token, stripped)

    def test_explicit_title_wins_and_keeps_original_in_the_body(self) -> None:
        original = "再记一下 周末计划 把书房整理扩成类似旧书店里一边查目录  一边做笔记的半天安排"
        title, body = mi.memo_title_and_body(original, title="周末计划：旧书店式整理")
        self.assertEqual(title, "周末计划：旧书店式整理")
        self.assertEqual(body, "周末计划 把书房整理扩成类似旧书店里一边查目录  一边做笔记的半天安排")

    def test_safe_filename_uses_fullwidth_colon_and_strips_other_illegal_characters(self) -> None:
        stem = mi.safe_filename_stem("周末计划:旧书店式整理")
        self.assertEqual(stem, "周末计划：旧书店式整理")
        self.assertNotRegex(stem, r'[<>:"/\\|?*]')
        mixed = mi.safe_filename_stem("查一下 a/b:c*d?")
        self.assertEqual(mixed, "查一下 a b：c d")
        self.assertNotRegex(mixed, r'[<>:"/\\|?*]')


class WriteMemoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()
        self.config = self.root / "config"
        self.config.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_args(self, *extra: str) -> list[str]:
        return [
            "write-memo",
            "--vault-root",
            str(self.vault),
            "--config-dir",
            str(self.config),
            *extra,
        ]

    def test_write_memo_then_dedup_and_conflict(self) -> None:
        first = run(*self.write_args("--original", EXAMPLE_TEXT, "--source", EXAMPLE_SOURCE, "--reported-at", EXAMPLE_AT))
        self.assertEqual(first.returncode, 0, first.stderr)
        payload = load_stdout(first)
        self.assertEqual(payload["action"], "written")
        self.assertEqual(payload["title"], EXAMPLE_TEXT)
        self.assertEqual(payload["relpath"], f"{mi.MEMO_DIR}/{EXAMPLE_TEXT}.md")
        dest = Path(payload["path"])
        self.assertTrue(dest.is_file())
        # Short memos use the filename as the title and do not repeat the body.
        self.assertEqual(dest.read_text(encoding="utf-8").strip(), "")
        self.assertNotIn("## Original", dest.read_text(encoding="utf-8"))
        self.assertNotIn("---", dest.read_text(encoding="utf-8"))

        index = json.loads((self.config / mi.INDEX_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(len(index["items"]), 1)
        self.assertNotIn("original", index["items"][0])
        self.assertNotIn("body", json.dumps(index, ensure_ascii=False))

        again = run(*self.write_args("--original", EXAMPLE_TEXT, "--source", EXAMPLE_SOURCE, "--reported-at", EXAMPLE_AT))
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(load_stdout(again)["action"], "duplicate")
        self.assertEqual(load_stdout(again)["path"], payload["path"])
        self.assertEqual(len(list((self.vault / mi.MEMO_DIR).glob("*.md"))), 1)

        dest.write_text("别人已经写过的同名笔记\n", encoding="utf-8")
        refused = run(
            *self.write_args(
                "--original",
                "另一条却会用同一个文件名的备忘",
                "--source",
                EXAMPLE_SOURCE,
                "--reported-at",
                "2026-11-14T10:00:00+08:00",
            )
        )
        # The pre-existing file keeps a different title; instead occupy the planned path.
        planned = run(
            "plan-memo",
            "--original",
            "记一下 临时冲突标题",
            "--source",
            EXAMPLE_SOURCE,
            "--reported-at",
            "2026-11-14T10:00:00+08:00",
        )
        self.assertEqual(planned.returncode, 0, planned.stderr)
        clash = self.vault / load_stdout(planned)["relpath"]
        clash.parent.mkdir(parents=True, exist_ok=True)
        clash.write_text("已有且内容不同的笔记\n", encoding="utf-8")
        refused = run(
            *self.write_args(
                "--original",
                "记一下 临时冲突标题",
                "--source",
                EXAMPLE_SOURCE,
                "--reported-at",
                "2026-11-14T10:00:00+08:00",
            )
        )
        self.assertEqual(refused.returncode, mi.EXIT_CONFLICT, refused.stdout + refused.stderr)
        self.assertIn("already exists with different content", load_stdout(refused)["error"])
        self.assertEqual(clash.read_text(encoding="utf-8"), "已有且内容不同的笔记\n")

    def test_write_memo_skips_unrelated_legacy_notes(self) -> None:
        memo_dir = self.vault / mi.MEMO_DIR
        memo_dir.mkdir()
        (memo_dir / "家庭旧笔记.md").write_text("只是一条旧笔记\n", encoding="utf-8")
        result = run(*self.write_args("--original", EXAMPLE_TEXT, "--source", EXAMPLE_SOURCE, "--reported-at", EXAMPLE_AT))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(load_stdout(result)["action"], "written")
        self.assertTrue((memo_dir / "家庭旧笔记.md").is_file())
        self.assertEqual((memo_dir / "家庭旧笔记.md").read_text(encoding="utf-8"), "只是一条旧笔记\n")

    def test_write_long_memo_keeps_original_as_body(self) -> None:
        original = "记一下 周末要去图书馆还书。另外把过期的会员卡续上，顺便看看展览。"
        result = run(*self.write_args("--original", original, "--source", EXAMPLE_SOURCE, "--reported-at", EXAMPLE_AT))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = load_stdout(result)
        self.assertEqual(payload["title"], "周末要去图书馆还书")
        self.assertTrue(payload["has_body"])
        note = Path(payload["path"]).read_text(encoding="utf-8")
        self.assertEqual(note, "周末要去图书馆还书。另外把过期的会员卡续上，顺便看看展览。\n")
        self.assertNotIn("记一下", note)
        self.assertNotIn("## Original", note)
        self.assertNotIn("idempotency_key", note)

    def test_write_memo_uses_explicit_title_and_fullwidth_colon(self) -> None:
        original = "再记一下 周末计划 把书房整理扩成类似旧书店里一边查目录  一边做笔记的半天安排"
        result = run(
            *self.write_args(
                "--original",
                original,
                "--source",
                EXAMPLE_SOURCE,
                "--reported-at",
                EXAMPLE_AT,
                "--title",
                "周末计划：旧书店式整理",
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = load_stdout(result)
        self.assertEqual(payload["title"], "周末计划：旧书店式整理")
        self.assertEqual(payload["filename"], "周末计划：旧书店式整理.md")
        note = Path(payload["path"]).read_text(encoding="utf-8")
        self.assertEqual(note, "周末计划 把书房整理扩成类似旧书店里一边查目录  一边做笔记的半天安排\n")
        self.assertNotIn("再记一下", note)

    def test_write_memo_from_legacy_item_uses_natural_links(self) -> None:
        created = mi.create_item(
            self.inbox,
            original="记一下 周末去图书馆还书",
            source=EXAMPLE_SOURCE,
            reported_at=EXAMPLE_AT,
        )
        path = Path(created["item"]["path"])
        related = "这是扩展，参见 [20261113-aaaaaaaa.md](20261113-aaaaaaaa.md)。"
        path.write_text(path.read_text(encoding="utf-8").rstrip() + f"\n\n## Related\n\n{related}\n", encoding="utf-8")
        written = run(
            *self.write_args(
                "--item",
                str(path),
                "--link-map",
                json.dumps({"20261113-aaaaaaaa": "旧点子标题"}, ensure_ascii=False),
            )
        )
        self.assertEqual(written.returncode, 0, written.stderr)
        payload = load_stdout(written)
        note = Path(payload["path"]).read_text(encoding="utf-8")
        self.assertNotIn("## Related", note)
        self.assertNotIn("## Original", note)
        self.assertIn("这是扩展，参见 [[旧点子标题]]。", note)
        self.assertNotIn("20261113-aaaaaaaa.md", note)

        updated = mi.set_status(
            path,
            "imported",
            imported_path=payload["relpath"],
            imported_at=EXAMPLE_LATER,
        )
        after = path.read_text(encoding="utf-8")
        self.assertEqual(updated["item"]["fields"]["status"], "imported")
        self.assertIn("## Related", after)
        self.assertIn("这是扩展，参见 [20261113-aaaaaaaa.md](20261113-aaaaaaaa.md)。", after)

    def test_same_entry_compares_plain_vault_notes(self) -> None:
        first = run(
            *self.write_args("--original", "记一下 周六去图书馆还书。另外把会员卡续上。", "--source", EXAMPLE_SOURCE, "--reported-at", EXAMPLE_AT),
            check=True,
        )
        path = load_stdout(first)["path"]
        same = run("same-entry", "--a", path, "--b", path)
        self.assertEqual(same.returncode, 0)
        self.assertTrue(load_stdout(same)["same_entry"])

    def test_same_entry_plain_notes_match_across_paths_when_body_matches(self) -> None:
        first = run(
            *self.write_args("--original", "记一下 周六去图书馆还书。另外把会员卡续上。", "--source", EXAMPLE_SOURCE, "--reported-at", EXAMPLE_AT),
            check=True,
        )
        src = Path(load_stdout(first)["path"])
        copy = self.root / "readback-copy.md"
        copy.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        same = run("same-entry", "--a", str(src), "--b", str(copy))
        self.assertEqual(same.returncode, 0)
        self.assertTrue(load_stdout(same)["same_entry"])

        different = self.root / "other-title.md"
        different.write_text("完全不同的正文\n", encoding="utf-8")
        mismatch = run("same-entry", "--a", str(src), "--b", str(different))
        self.assertEqual(mismatch.returncode, mi.EXIT_IO)
        self.assertFalse(load_stdout(mismatch)["same_entry"])

    def test_same_entry_title_only_notes_require_matching_stems(self) -> None:
        first = run(
            *self.write_args("--original", EXAMPLE_TEXT, "--source", EXAMPLE_SOURCE, "--reported-at", EXAMPLE_AT),
            check=True,
        )
        src = Path(load_stdout(first)["path"])
        self.assertEqual(src.read_text(encoding="utf-8").strip(), "")
        same_name = self.root / f"{src.stem}.md"
        same_name.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        same = run("same-entry", "--a", str(src), "--b", str(same_name))
        self.assertEqual(same.returncode, 0, same.stderr)
        self.assertTrue(load_stdout(same)["same_entry"])

        other_name = self.root / "另一个标题.md"
        other_name.write_text("", encoding="utf-8")
        mismatch = run("same-entry", "--a", str(src), "--b", str(other_name))
        self.assertEqual(mismatch.returncode, mi.EXIT_IO)
        self.assertFalse(load_stdout(mismatch)["same_entry"])

    def test_write_memo_index_hit_requires_matching_file(self) -> None:
        first = run(*self.write_args("--original", EXAMPLE_TEXT, "--source", EXAMPLE_SOURCE, "--reported-at", EXAMPLE_AT))
        self.assertEqual(first.returncode, 0, first.stderr)
        dest = Path(load_stdout(first)["path"])

        dest.write_text("已被改过的内容\n", encoding="utf-8")
        edited = run(*self.write_args("--original", EXAMPLE_TEXT, "--source", EXAMPLE_SOURCE, "--reported-at", EXAMPLE_AT))
        self.assertEqual(edited.returncode, mi.EXIT_REFUSED, edited.stdout + edited.stderr)
        self.assertIn("no longer matches", load_stdout(edited)["error"])

        dest.unlink()
        missing = run(*self.write_args("--original", EXAMPLE_TEXT, "--source", EXAMPLE_SOURCE, "--reported-at", EXAMPLE_AT))
        self.assertEqual(missing.returncode, mi.EXIT_REFUSED, missing.stdout + missing.stderr)
        self.assertIn("missing on disk", load_stdout(missing)["error"])


class RepoHygieneTests(unittest.TestCase):

    def test_repo_sample_texts_stay_non_sensitive(self) -> None:
        samples = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SCRIPT_DIR, SCRIPT_DIR.parent / "references")
            if path.exists()
            for path in path.rglob("*")
            if path.is_file() and path.suffix in {".md", ".py"} and "__pycache__" not in path.parts
        )
        self.assertIn(EXAMPLE_TEXT, samples)


if __name__ == "__main__":
    unittest.main()
