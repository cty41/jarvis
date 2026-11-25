#!/usr/bin/env python3
"""Deterministic helpers for receiving and importing non-sensitive memos.

Judgment (whether a memo is sensitive, where it should be classified in a
notes library) stays in SKILL.md. This module only handles item files,
status transitions, vault-path config, and verified local writes.
"""

from __future__ import annotations

import argparse
import os
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

STATUSES = ("pending", "prepared", "imported", "needs-review")
TRANSITIONS = {
    "pending": frozenset({"prepared", "imported", "needs-review"}),
    "prepared": frozenset({"pending", "imported", "needs-review"}),
    "needs-review": frozenset({"pending", "prepared", "imported"}),
    "imported": frozenset({"needs-review"}),
}
REQUIRED_FIELDS = ("id", "idempotency_key", "source", "reported_at", "status")
OPTIONAL_EMPTY_FIELDS = ("occurred_at", "imported_path", "imported_at")
ISO_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})$"
)
ID_RE = re.compile(r"^\d{8}-[0-9a-f]{8}$")
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "alfred"
DEFAULT_VAULT_CONFIG = "default-vault.json"
SENSITIVE_VAULT_CONFIG = "records-vault.json"
MEMO_DIR = "备忘"
INDEX_FILENAME = "memo-index.json"
INDEX_VERSION = 1
# Fallback length for auto titles only. Longer text is summarized even
# when it is a single sentence. An explicit title from the assistant wins.
SOFT_TITLE_LIMIT = 30
VAULT_REQUIRED_FIELDS = ("id", "idempotency_key", "source", "reported_at")
TRIGGER_PREFIX_RE = re.compile(
    r"^(?:再\s*)?记一下[，,。、：:.！!？?\s]*",
    flags=re.UNICODE,
)
SENTENCE_END_RE = re.compile(r"(?<=[。！？!?])")
UNSAFE_FILENAME_CHARS = '<>:"/\\|?*'
WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)

# Exit codes
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CONFLICT = 3
EXIT_IO = 4
EXIT_REFUSED = 5


class ItemError(ValueError):
    """Invalid item content or request."""


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def idempotency_key(original: str, source: str) -> str:
    payload = f"{normalize_text(original)}\n{normalize_text(source)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_instant(value: str) -> datetime:
    if not value or not ISO_INSTANT_RE.match(value):
        raise ItemError(f"timestamp must be ISO-8601 with an explicit offset or Z: {value!r}")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def date_stamp(reported_at: str) -> str:
    return parse_instant(reported_at).strftime("%Y%m%d")


def make_id(reported_at: str, key: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ItemError("idempotency_key must be a sha256 hex digest")
    return f"{date_stamp(reported_at)}-{key[:8]}"


def quote_frontmatter(value: str) -> str:
    if value == "":
        return '""'
    if re.search(r'[:#\[\]{}\n"\\]', value) or value != value.strip():
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def unquote_frontmatter(value: str) -> str:
    value = value.strip()
    if value in {"", '""', "''", "~", "null"}:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        inner = value[1:-1]
        return inner.replace("\\\\", "\\").replace('\\"', '"')
    return value


ITEM_FIELD_ORDER = [
    "id",
    "idempotency_key",
    "source",
    "reported_at",
    "occurred_at",
    "status",
    "imported_path",
    "imported_at",
]


def dump_frontmatter(fields: dict[str, str], keys: list[str] | None = None) -> str:
    if keys is None:
        keys = list(ITEM_FIELD_ORDER)
        keys.extend(key for key in fields if key not in keys)
    lines = ["---"]
    seen = set()
    for key in keys:
        lines.append(f"{key}: {quote_frontmatter(fields.get(key, ''))}")
        seen.add(key)
    for key, value in fields.items():
        if key not in seen:
            lines.append(f"{key}: {quote_frontmatter(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        raise ItemError("item must start with YAML frontmatter")
    rest = text[3:]
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    else:
        raise ItemError("item must start with YAML frontmatter")
    end = re.search(r"\n---\r?\n", rest)
    if not end:
        raise ItemError("frontmatter is not closed")
    block = rest[: end.start()]
    body = rest[end.end() :]
    fields: dict[str, str] = {}
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ItemError(f"invalid frontmatter line: {raw_line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ItemError(f"invalid frontmatter key: {key!r}")
        if key in fields:
            raise ItemError(f"duplicate frontmatter key: {key}")
        fields[key] = unquote_frontmatter(value)
    return fields, body


def split_body_sections(body: str) -> dict[str, str]:
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\n"):
        text = text[1:]
    matches = list(re.finditer(r"^## ([^\n]+)\n", text, flags=re.MULTILINE))
    if not matches:
        raise ItemError("item body must contain ## Original")
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[name] = text[start:end]
    if "Original" not in sections:
        raise ItemError("item body must contain ## Original")
    return sections


def section_text(sections: dict[str, str], name: str) -> str:
    return normalize_text(sections.get(name, ""))



def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_memo_trigger(original: str) -> str:
    text = normalize_text(original)
    stripped = TRIGGER_PREFIX_RE.sub("", text).strip()
    return stripped or text


def split_sentences(text: str) -> list[str]:
    parts = SENTENCE_END_RE.split(text)
    sentences = [part.strip() for part in parts if part.strip()]
    return sentences


def conservative_title(text: str, limit: int = SOFT_TITLE_LIMIT) -> str:
    """Build a short title using only words already in the text."""
    text = collapse_whitespace(text)
    if not text:
        return "备忘"
    sentences = split_sentences(text)
    first = (sentences[0] if sentences else text).rstrip("。！？!? ")
    if len(first) <= limit:
        return first
    break_chars = "，,、；; "
    cut = None
    for index, char in enumerate(first):
        if char in break_chars and 1 <= index <= limit:
            cut = index
        if index >= limit and cut:
            break
        if index >= limit and cut is None:
            break
    if cut:
        return first[:cut].rstrip("，,、；; ")
    if len(first) > limit:
        # Prefer a space break for mixed Chinese/English; otherwise a plain prefix.
        space = first.rfind(" ", 0, limit + 1)
        if space >= max(8, limit // 2):
            return first[:space].rstrip()
        return first[:limit].rstrip("，,、；; ")
    return first


def memo_title_and_body(original: str, title: str | None = None) -> tuple[str, str]:
    """Return a casual title and, when needed, the original text as the body.

    Prefer an explicit title when the assistant has already chosen a short,
    faithful one. Otherwise, text after「记一下」that is still short becomes
    the title and is not repeated in the body. Longer text — including a
    long single sentence — gets a conservative auto title, with the wording
    after the trigger kept as the body. The length limit is only a fallback.
    """
    original_text = normalize_text(original)
    stripped = strip_memo_trigger(original_text)

    def as_title(value: str) -> str:
        return collapse_whitespace(value).rstrip("。！？!? ")

    stripped_title = as_title(stripped)
    sentences = split_sentences(stripped)
    if title:
        chosen = as_title(title)
        if not chosen:
            raise ItemError("title must not be empty")
        if chosen == stripped_title and len(sentences) <= 1 and len(stripped_title) <= SOFT_TITLE_LIMIT:
            return chosen, ""
        return chosen, stripped
    # Short single-sentence notes can use the text as the title. A long
    # sentence or more than one sentence is summarized; the length limit
    # is only a fallback, not a reason to keep a long sentence as-is.
    if len(sentences) <= 1 and len(stripped_title) <= SOFT_TITLE_LIMIT:
        return stripped_title, ""
    return conservative_title(stripped), stripped


def safe_filename_stem(title: str) -> str:
    name = collapse_whitespace(title)
    # Windows forbids ASCII colons in filenames; keep a readable fullwidth colon.
    name = name.replace(":", "：")
    table = str.maketrans({char: " " for char in UNSAFE_FILENAME_CHARS if char != ":"})
    name = collapse_whitespace(name.translate(table))
    name = name.rstrip(" .")
    if not name:
        name = "备忘"
    if name.upper() in WINDOWS_RESERVED:
        name = f"{name} 备忘"
    return name


def memo_filename(title: str) -> str:
    return f"{safe_filename_stem(title)}.md"


def memo_relpath_for_title(title: str, memo_dir: str = MEMO_DIR) -> str:
    if not memo_dir or Path(memo_dir).is_absolute() or ".." in Path(memo_dir).parts:
        raise ItemError("memo directory must be a relative path inside the vault")
    return f"{memo_dir}/{memo_filename(title)}"


LOOSE_ID_RE = re.compile(r"\d{8}-[0-9a-f]{8}")


def extract_legacy_id(text: str) -> str | None:
    match = LOOSE_ID_RE.search(text or "")
    return match.group(0) if match else None


def rewrite_legacy_refs(text: str, id_to_title: dict[str, str] | None) -> str:
    if not text:
        return ""
    mapping = id_to_title or {}

    def replace_link(match: re.Match[str]) -> str:
        label, dest = match.group(1), match.group(2)
        item_id = extract_legacy_id(dest) or extract_legacy_id(label)
        if item_id and item_id in mapping:
            return f"[[{mapping[item_id]}]]"
        return match.group(0)

    updated = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", replace_link, text)
    bare = ID_RE.findall(updated)
    for item_id in bare:
        if item_id in mapping and f"[[{mapping[item_id]}]]" not in updated:
            updated = re.sub(rf"\b{item_id}(?:\.md)?\b", f"[[{mapping[item_id]}]]", updated)
    return normalize_text(updated)


def natural_related_text(related: str, id_to_title: dict[str, str] | None = None) -> str:
    text = rewrite_legacy_refs(related, id_to_title)
    return text


def render_plain_note(body: str = "", related: str = "") -> str:
    parts: list[str] = []
    body = normalize_text(body)
    related = normalize_text(related)
    if body:
        parts.append(body)
    if related:
        parts.append(related)
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n"


def index_path(config_dir: Path | None = None) -> Path:
    return (config_dir or default_config_dir()) / INDEX_FILENAME


def load_memo_index(config_dir: Path | None = None) -> dict[str, Any]:
    path = index_path(config_dir)
    if not path.is_file():
        return {"version": INDEX_VERSION, "items": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ItemError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ItemError(f"{path} must contain a JSON object")
    items = data.get("items", [])
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ItemError(f"{path} items must be a list")
    cleaned: list[dict[str, str]] = []
    for row in items:
        if not isinstance(row, dict):
            raise ItemError(f"{path} has a non-object index entry")
        item_id = row.get("id", "")
        key = row.get("idempotency_key", "")
        relpath = row.get("relpath", "")
        if not item_id or not key or not relpath:
            raise ItemError(f"{path} index entries require id, idempotency_key, and relpath")
        if any(forbidden in row for forbidden in ("original", "body", "text", "content")):
            raise ItemError(f"{path} must not store memo text")
        cleaned.append(
            {
                "id": str(item_id),
                "idempotency_key": str(key),
                "relpath": str(relpath).replace("\\", "/"),
            }
        )
    return {"version": int(data.get("version") or INDEX_VERSION), "items": cleaned}


def save_memo_index(index: dict[str, Any], config_dir: Path | None = None) -> Path:
    path = index_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": INDEX_VERSION,
        "items": [
            {
                "id": row["id"],
                "idempotency_key": row["idempotency_key"],
                "relpath": row["relpath"],
            }
            for row in index.get("items", [])
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(encoded, encoding="utf-8", newline="\n")
    tmp.replace(path)
    return path


def index_find_by_key(index: dict[str, Any], key: str) -> dict[str, str] | None:
    for row in index.get("items", []):
        if row.get("idempotency_key") == key:
            return row
    return None


def index_find_by_relpath(index: dict[str, Any], relpath: str) -> dict[str, str] | None:
    wanted = relpath.replace("\\", "/")
    for row in index.get("items", []):
        if row.get("relpath") == wanted:
            return row
    return None


def index_upsert(index: dict[str, Any], *, item_id: str, key: str, relpath: str) -> dict[str, Any]:
    relpath = relpath.replace("\\", "/")
    items = [row for row in index.get("items", []) if row.get("idempotency_key") != key]
    items.append({"id": item_id, "idempotency_key": key, "relpath": relpath})
    index = {"version": INDEX_VERSION, "items": items}
    return index


def titles_from_index(index: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in index.get("items", []):
        stem = Path(row["relpath"]).stem
        mapping[row["id"]] = stem
    return mapping


def plan_memo(
    original: str,
    source: str,
    reported_at: str,
    occurred_at: str = "",
    *,
    extra_related: str = "",
    id_to_title: dict[str, str] | None = None,
    memo_dir: str = MEMO_DIR,
    item_id: str | None = None,
    key: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    original_text = normalize_text(original)
    if not original_text:
        raise ItemError("original text must not be empty")
    source_value = normalize_text(source)
    if not source_value:
        raise ItemError("source is required")
    key = key or idempotency_key(original_text, source_value)
    item_id = item_id or make_id(reported_at, key)
    title, body = memo_title_and_body(original_text, title=title)
    related = natural_related_text(extra_related, id_to_title)
    note_text = render_plain_note(body, related)
    relpath = memo_relpath_for_title(title, memo_dir=memo_dir)
    return {
        "id": item_id,
        "idempotency_key": key,
        "source": source_value,
        "reported_at": reported_at,
        "occurred_at": occurred_at or "",
        "title": title,
        "filename": memo_filename(title),
        "relpath": relpath,
        "body": note_text,
        "has_body": bool(note_text.strip()),
    }


def extra_sections_from_item(item: dict[str, Any]) -> dict[str, str]:
    extras: dict[str, str] = {}
    for name, value in item.get("sections", {}).items():
        if name in {"Original", "Corrections", "Conflicts"}:
            continue
        extras[name] = value
    return extras


def render_body(
    original: str,
    corrections: str = "",
    conflicts: str = "",
    extra_sections: dict[str, str] | None = None,
) -> str:
    parts = ["## Original", "", normalize_text(original), "", "## Corrections"]
    corrections = normalize_text(corrections)
    if corrections:
        parts.extend(["", corrections])
    conflicts = normalize_text(conflicts)
    if conflicts:
        parts.extend(["", "## Conflicts", "", conflicts])
    if extra_sections:
        for name, value in extra_sections.items():
            if name in {"Original", "Corrections", "Conflicts"}:
                continue
            parts.extend(["", f"## {name}", ""])
            normalized = normalize_text(value)
            if normalized:
                parts.append(normalized)
    return "\n".join(parts).rstrip() + "\n"


def render_item(
    fields: dict[str, str],
    original: str,
    corrections: str = "",
    conflicts: str = "",
    extra_sections: dict[str, str] | None = None,
) -> str:
    return dump_frontmatter(fields) + "\n" + render_body(
        original, corrections, conflicts, extra_sections=extra_sections
    )


def parse_item_text(text: str) -> dict[str, Any]:
    fields, body = parse_frontmatter(text)
    sections = split_body_sections(body)
    original = section_text(sections, "Original")
    if not original:
        raise ItemError("Original section must not be empty")
    item = {
        "fields": fields,
        "original": original,
        "corrections": section_text(sections, "Corrections"),
        "conflicts": section_text(sections, "Conflicts"),
        "sections": sections,
    }
    validate_fields(fields, original)
    return item


def validate_fields(fields: dict[str, str], original: str) -> None:
    missing = [key for key in REQUIRED_FIELDS if not fields.get(key)]
    if missing:
        raise ItemError("missing required fields: " + ", ".join(missing))
    status = fields["status"]
    if status not in STATUSES:
        raise ItemError(f"invalid status: {status!r}")
    if not ID_RE.match(fields["id"]):
        raise ItemError(f"id must be YYYYMMDD- plus 8 hex digits: {fields['id']!r}")
    key = fields["idempotency_key"]
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ItemError("idempotency_key must be a sha256 hex digest")
    parse_instant(fields["reported_at"])
    if fields.get("occurred_at"):
        parse_instant(fields["occurred_at"])
    if fields.get("imported_at"):
        parse_instant(fields["imported_at"])
    expected_key = idempotency_key(original, fields["source"])
    if key != expected_key:
        raise ItemError("idempotency_key does not match original text and source")
    expected_id = make_id(fields["reported_at"], key)
    if fields["id"] != expected_id:
        raise ItemError("id does not match reported_at and idempotency_key")
    if status == "imported" and not fields.get("imported_path"):
        raise ItemError("imported status requires imported_path")


def items_dir(inbox_root: Path) -> Path:
    return inbox_root / "items"


def item_path(inbox_root: Path, item_id: str) -> Path:
    return items_dir(inbox_root) / f"{item_id}.md"


def read_item(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    item = parse_item_text(text)
    if path.name != f"{item['fields']['id']}.md":
        raise ItemError(f"filename {path.name!r} does not match id {item['fields']['id']!r}")
    item["path"] = path
    item["text"] = text
    return item


def write_item_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def list_items(inbox_root: Path) -> list[Path]:
    directory = items_dir(inbox_root)
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.md") if path.is_file())


def find_by_key(inbox_root: Path, key: str) -> dict[str, Any] | None:
    for path in list_items(inbox_root):
        try:
            item = read_item(path)
        except ItemError:
            continue
        if item["fields"]["idempotency_key"] == key:
            return item
    return None


def create_item(
    inbox_root: Path,
    original: str,
    source: str,
    reported_at: str,
    occurred_at: str = "",
) -> dict[str, Any]:
    original = normalize_text(original)
    source = normalize_text(source)
    if not original:
        raise ItemError("original text is required")
    if not source:
        raise ItemError("source is required")
    key = idempotency_key(original, source)
    item_id = make_id(reported_at, key)
    existing = find_by_key(inbox_root, key)
    if existing:
        return {"action": "duplicate", "item": existing}
    path = item_path(inbox_root, item_id)
    if path.exists():
        current = read_item(path)
        if normalize_text(current["original"]) == original and current["fields"]["source"] == source:
            return {"action": "duplicate", "item": current}
        conflict_block = _append_block(
            current["conflicts"],
            reported_at,
            f"source: {source}\n\n{original}",
        )
        fields = dict(current["fields"])
        fields["status"] = "needs-review"
        text = render_item(fields, current["original"], current["corrections"], conflict_block)
        write_item_file(path, text)
        updated = read_item(path)
        return {"action": "conflict", "item": updated}
    fields = {
        "id": item_id,
        "idempotency_key": key,
        "source": source,
        "reported_at": reported_at,
        "occurred_at": occurred_at,
        "status": "pending",
        "imported_path": "",
        "imported_at": "",
    }
    text = render_item(fields, original)
    write_item_file(path, text)
    return {"action": "created", "item": read_item(path)}


def _append_block(existing: str, at: str, text: str) -> str:
    parse_instant(at)
    block = f"### {at}\n\n{normalize_text(text)}"
    existing = normalize_text(existing)
    if not existing:
        return block + "\n"
    return existing + "\n\n" + block + "\n"


def append_correction(path: Path, text: str, at: str) -> dict[str, Any]:
    item = read_item(path)
    original_before = item["original"]
    fields_before = dict(item["fields"])
    corrections = _append_block(item["corrections"], at, text)
    rendered = render_item(fields_before, original_before, corrections, item["conflicts"])
    write_item_file(path, rendered)
    updated = read_item(path)
    if updated["original"] != original_before:
        raise ItemError("internal error: original text changed while appending a correction")
    if updated["fields"] != fields_before:
        raise ItemError("internal error: frontmatter changed while appending a correction")
    return {"action": "appended", "item": updated}


def set_status(
    path: Path,
    status: str,
    imported_path: str = "",
    imported_at: str = "",
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ItemError(f"invalid status: {status!r}")
    item = read_item(path)
    current = item["fields"]["status"]
    if status != current and status not in TRANSITIONS[current]:
        raise ItemError(f"cannot change status from {current} to {status}")
    fields = dict(item["fields"])
    fields["status"] = status
    if imported_path:
        fields["imported_path"] = imported_path
    if imported_at:
        parse_instant(imported_at)
        fields["imported_at"] = imported_at
    rendered = render_item(
        fields,
        item["original"],
        item["corrections"],
        item["conflicts"],
        extra_sections=extra_sections_from_item(item),
    )
    # Validate before write so a bad imported row is not saved.
    parse_item_text(rendered)
    write_item_file(path, rendered)
    return {"action": "status-updated", "item": read_item(path)}


def validate_inbox(inbox_root: Path) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    directory = items_dir(inbox_root)
    if not directory.exists():
        return results
    for path in sorted(directory.iterdir()):
        if path.name == ".gitkeep" or not path.is_file():
            continue
        if path.suffix != ".md":
            results.append({"path": str(path), "error": "item files must use the .md extension"})
            continue
        try:
            read_item(path)
        except ItemError as exc:
            results.append({"path": str(path), "error": str(exc)})
    return results


def default_config_dir() -> Path:
    override = os.environ.get("MEMO_CONFIG_DIR") or os.environ.get("JARVIS_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return DEFAULT_CONFIG_DIR


def _read_vault_path(config_dir: Path, filename: str) -> str | None:
    path = config_dir / filename
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ItemError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ItemError(f"{path} must contain a JSON object")
    value = data.get("vaultPath")
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ItemError(f"vaultPath in {path} must be a string")
    return value


def resolve_vaults(config_dir: Path | None = None) -> dict[str, str | None]:
    directory = config_dir or default_config_dir()
    return {
        "config_dir": str(directory),
        "default_vault_path": _read_vault_path(directory, DEFAULT_VAULT_CONFIG),
        "sensitive_vault_path": _read_vault_path(directory, SENSITIVE_VAULT_CONFIG),
    }


def is_skill_pack_checkout(path: Path) -> bool:
    """Return True if path lives inside a skill-pack checkout.

    A checkout is recognized when an ancestor contains memo-inbox/SKILL.md,
    or when the path itself is the memo-inbox skill directory. This must not
    depend on a historical inbox/ folder, which public checkouts do not ship.
    """
    current = path.resolve()
    for candidate in (current, *current.parents):
        skill_md = candidate / "SKILL.md"
        if candidate.name == "memo-inbox" and skill_md.is_file():
            return True
        if (candidate / "memo-inbox" / "SKILL.md").is_file():
            return True
    return False


def safe_dest(vault_root: Path, dest_relpath: str) -> Path:
    if not dest_relpath or Path(dest_relpath).is_absolute():
        raise ItemError("destination must be a relative path inside the vault")
    parts = Path(dest_relpath).parts
    if ".." in parts or any(part in {".", ""} for part in parts):
        raise ItemError("destination must be a relative path inside the vault")
    root = vault_root.resolve()
    dest = (root / dest_relpath).resolve()
    try:
        dest.relative_to(root)
    except ValueError as exc:
        raise ItemError("destination must be a relative path inside the vault") from exc
    if is_skill_pack_checkout(dest) or is_skill_pack_checkout(root):
        raise ItemError("refusing to write notes into the skill-pack checkout")
    return dest


def render_vault_note(item: dict[str, Any], mode: str = "original") -> str:
    if mode not in {"original", "prepared"}:
        raise ItemError(f"unsupported vault note mode: {mode}")
    fields = item["fields"]
    header = {
        "id": fields["id"],
        "idempotency_key": fields["idempotency_key"],
        "source": fields["source"],
        "reported_at": fields["reported_at"],
        "occurred_at": fields.get("occurred_at", ""),
    }
    body = render_body(
        item["original"],
        item["corrections"],
        item["conflicts"],
        extra_sections=extra_sections_from_item(item),
    )
    if mode == "prepared":
        body = body.replace("## Original", "## Draft", 1)
    keys = ["id", "idempotency_key", "source", "reported_at", "occurred_at"]
    return dump_frontmatter(header, keys=keys) + "\n" + body


def validate_vault_fields(fields: dict[str, str], original: str) -> None:
    missing = [key for key in VAULT_REQUIRED_FIELDS if not fields.get(key)]
    if missing:
        raise ItemError("missing required fields: " + ", ".join(missing))
    if not ID_RE.match(fields["id"]):
        raise ItemError(f"id must be YYYYMMDD- plus 8 hex digits: {fields['id']!r}")
    key = fields["idempotency_key"]
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ItemError("idempotency_key must be a sha256 hex digest")
    parse_instant(fields["reported_at"])
    if fields.get("occurred_at"):
        parse_instant(fields["occurred_at"])
    expected_key = idempotency_key(original, fields["source"])
    if key != expected_key:
        raise ItemError("idempotency_key does not match original text and source")
    expected_id = make_id(fields["reported_at"], key)
    if fields["id"] != expected_id:
        raise ItemError("id does not match reported_at and idempotency_key")


def parse_vault_memo_text(text: str) -> dict[str, Any]:
    fields, body = parse_frontmatter(text)
    sections = split_body_sections(body)
    original = section_text(sections, "Original")
    if not original:
        raise ItemError("Original section must not be empty")
    item = {
        "fields": fields,
        "original": original,
        "corrections": section_text(sections, "Corrections"),
        "conflicts": section_text(sections, "Conflicts"),
        "sections": sections,
    }
    validate_vault_fields(fields, original)
    return item


def read_vault_memo(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    item = parse_vault_memo_text(text)
    if path.name != f"{item['fields']['id']}.md":
        raise ItemError(f"filename {path.name!r} does not match id {item['fields']['id']!r}")
    item["path"] = path
    item["text"] = text
    return item


def memo_relpath(item_id: str, memo_dir: str = MEMO_DIR) -> str:
    if not memo_dir or Path(memo_dir).is_absolute() or ".." in Path(memo_dir).parts:
        raise ItemError("memo directory must be a relative path inside the vault")
    return f"{memo_dir}/{item_id}.md"


def list_vault_memos(vault_root: Path, memo_dir: str = MEMO_DIR) -> list[Path]:
    directory = vault_root / memo_dir
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.md") if path.is_file())


def find_vault_memo_by_key(
    vault_root: Path, key: str, memo_dir: str = MEMO_DIR
) -> dict[str, Any] | None:
    for path in list_vault_memos(vault_root, memo_dir=memo_dir):
        try:
            item = read_vault_memo(path)
        except ItemError:
            continue
        if item["fields"]["idempotency_key"] == key:
            return item
    return None


def write_memo(
    vault_root: Path,
    *,
    original: str | None = None,
    source: str | None = None,
    reported_at: str | None = None,
    occurred_at: str = "",
    item: dict[str, Any] | None = None,
    memo_dir: str = MEMO_DIR,
    config_dir: Path | None = None,
    id_to_title: dict[str, str] | None = None,
    relocate: bool = False,
    title: str | None = None,
) -> dict[str, Any]:
    extras: dict[str, str] = {}
    if item is not None:
        fields = item["fields"]
        original_text = item["original"]
        source_value = fields["source"]
        reported = fields["reported_at"]
        occurred = fields.get("occurred_at", "")
        extras = extra_sections_from_item(item)
        key = fields["idempotency_key"]
        item_id = fields["id"]
    else:
        original_text = normalize_text(original or "")
        if not original_text:
            raise ItemError("original text must not be empty")
        source_value = source or ""
        if not source_value:
            raise ItemError("source is required")
        if not reported_at:
            raise ItemError("reported_at is required")
        reported = reported_at
        occurred = occurred_at or ""
        key = idempotency_key(original_text, source_value)
        item_id = make_id(reported, key)

    config = Path(config_dir) if config_dir is not None else default_config_dir()
    index = load_memo_index(config)
    mapping = titles_from_index(index)
    if id_to_title:
        mapping.update(id_to_title)
    planned = plan_memo(
        original_text,
        source_value,
        reported,
        occurred,
        extra_related=extras.get("Related", ""),
        id_to_title=mapping,
        memo_dir=memo_dir,
        item_id=item_id,
        key=key,
        title=title,
    )
    relpath = planned["relpath"]
    dest = safe_dest(vault_root, relpath)
    existing = index_find_by_key(index, planned["idempotency_key"])
    occupant = index_find_by_relpath(index, relpath)

    def payload(action: str, path: Path, old_relpath: str = "") -> dict[str, Any]:
        return {
            "action": action,
            "path": str(path),
            "relpath": relpath if path == dest else path.resolve().relative_to(vault_root.resolve()).as_posix(),
            "old_relpath": old_relpath,
            "id": planned["id"],
            "idempotency_key": planned["idempotency_key"],
            "source": planned["source"],
            "reported_at": planned["reported_at"],
            "occurred_at": planned["occurred_at"],
            "title": planned["title"],
            "filename": planned["filename"],
            "has_body": planned["has_body"],
        }

    if existing is not None and not relocate:
        existing_path = vault_root / existing["relpath"]
        if not existing_path.is_file():
            raise ItemError(
                "indexed memo is missing on disk; refusing to report it as already saved"
            )
        current = existing_path.read_text(encoding="utf-8")
        if normalize_text(current) != normalize_text(planned["body"]):
            raise ItemError(
                "indexed memo no longer matches the planned content; refusing to report it as already saved"
            )
        return payload("duplicate", existing_path, existing["relpath"])

    if occupant is not None and occupant["idempotency_key"] != planned["idempotency_key"]:
        raise ItemError("destination already exists with different content")

    if dest.exists():
        current = dest.read_text(encoding="utf-8")
        if normalize_text(current) == normalize_text(planned["body"]):
            index = index_upsert(
                index,
                item_id=planned["id"],
                key=planned["idempotency_key"],
                relpath=relpath,
            )
            save_memo_index(index, config)
            old = existing["relpath"] if existing else ""
            return payload("duplicate", dest, old)
        raise ItemError("destination already exists with different content")

    written = write_vault_note(dest, planned["body"])
    index = index_upsert(
        index,
        item_id=planned["id"],
        key=planned["idempotency_key"],
        relpath=relpath,
    )
    save_memo_index(index, config)
    action = "relocated" if existing is not None and existing.get("relpath") not in {"", relpath} else "written"
    old = existing["relpath"] if existing else ""
    return payload(action, Path(written["path"]), old)


def write_vault_note(dest: Path, text: str) -> dict[str, Any]:
    expected = text.replace("\r\n", "\n")
    if dest.exists():
        current = dest.read_text(encoding="utf-8").replace("\r\n", "\n")
        if normalize_text(current) != normalize_text(expected):
            raise ItemError("destination already exists with different content")
        return {"action": "already-present", "path": str(dest)}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(expected, encoding="utf-8", newline="\n")
    readback = dest.read_text(encoding="utf-8").replace("\r\n", "\n")
    if normalize_text(readback) != normalize_text(expected):
        raise ItemError("read-back of the written note did not match")
    return {"action": "written", "path": str(dest)}


def item_payload(item: dict[str, Any]) -> dict[str, Any]:
    fields = item["fields"]
    payload = {
        "id": fields["id"],
        "path": str(item.get("path", "")),
        "status": fields["status"],
        "idempotency_key": fields["idempotency_key"],
        "source": fields["source"],
        "reported_at": fields["reported_at"],
        "occurred_at": fields.get("occurred_at", ""),
        "imported_path": fields.get("imported_path", ""),
        "imported_at": fields.get("imported_at", ""),
        "original": item["original"],
        "corrections": item["corrections"],
        "conflicts": item["conflicts"],
    }
    return payload


def emit(data: dict[str, Any], code: int = EXIT_OK) -> int:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return code


def fail(message: str, code: int = EXIT_USAGE) -> int:
    json.dump({"ok": False, "error": message}, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    print(message, file=sys.stderr)
    return code


def add_inbox_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--inbox-root", type=Path, required=True, help="Path to the inbox/ directory")


def add_item_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--item", type=Path, required=True, help="Path to an inbox item file")


def cmd_create(args: argparse.Namespace) -> int:
    original = args.original if args.original is not None else args.original_file.read_text(encoding="utf-8")
    try:
        result = create_item(
            args.inbox_root,
            original=original,
            source=args.source,
            reported_at=args.reported_at,
            occurred_at=args.occurred_at or "",
        )
    except ItemError as exc:
        return fail(str(exc), EXIT_USAGE)
    payload = {"ok": True, "action": result["action"], **item_payload(result["item"])}
    code = EXIT_OK if result["action"] != "conflict" else EXIT_CONFLICT
    return emit(payload, code)


def cmd_append_correction(args: argparse.Namespace) -> int:
    text = args.text if args.text is not None else args.text_file.read_text(encoding="utf-8")
    try:
        result = append_correction(args.item, text=text, at=args.at)
    except ItemError as exc:
        return fail(str(exc), EXIT_USAGE)
    return emit({"ok": True, "action": result["action"], **item_payload(result["item"])})


def cmd_set_status(args: argparse.Namespace) -> int:
    try:
        result = set_status(
            args.item,
            status=args.status,
            imported_path=args.imported_path or "",
            imported_at=args.imported_at or "",
        )
    except ItemError as exc:
        return fail(str(exc), EXIT_USAGE)
    return emit({"ok": True, "action": result["action"], **item_payload(result["item"])})


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        if args.item:
            item = read_item(args.item)
            return emit({"ok": True, "action": "validated", **item_payload(item)})
        if not args.inbox_root:
            return fail("--item or --inbox-root is required", EXIT_USAGE)
        errors = validate_inbox(args.inbox_root)
    except ItemError as exc:
        return fail(str(exc), EXIT_USAGE)
    if errors:
        return emit({"ok": False, "action": "validated", "errors": errors}, EXIT_USAGE)
    return emit({"ok": True, "action": "validated", "errors": []})


def cmd_show(args: argparse.Namespace) -> int:
    try:
        item = read_item(args.item)
    except ItemError as exc:
        return fail(str(exc), EXIT_USAGE)
    return emit({"ok": True, "action": "show", **item_payload(item)})


def _read_comparable(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if text.lstrip().startswith("---"):
        try:
            item = read_item(path)
            item["plain"] = False
            item["stem"] = path.stem
            return item
        except ItemError:
            try:
                item = read_vault_memo(path)
                item["plain"] = False
                item["stem"] = path.stem
                return item
            except ItemError:
                pass
    return {
        "fields": {"id": "", "idempotency_key": ""},
        "original": normalize_text(text),
        "plain": True,
        "stem": path.stem,
    }


def same_entry_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare two memo copies.

    Structured leftover items match on id, idempotency key, and original
    text. Current vault notes are plain files: non-empty bodies match on
    normalized content even across paths; title-only (empty-body) notes
    also require the filename stem to match, because the title is the
    identity.
    """
    if left.get("plain") and right.get("plain"):
        if left["original"] != right["original"]:
            return False
        if left["original"].strip():
            return True
        return left.get("stem") == right.get("stem")
    return (
        left["fields"]["id"] == right["fields"]["id"]
        and left["fields"]["idempotency_key"] == right["fields"]["idempotency_key"]
        and left["original"] == right["original"]
        and bool(left["fields"]["id"])
    )


def cmd_same_entry(args: argparse.Namespace) -> int:
    try:
        left = _read_comparable(args.a)
        right = _read_comparable(args.b)
    except ItemError as exc:
        return fail(str(exc), EXIT_USAGE)
    matched = same_entry_match(left, right)
    payload = {"ok": True, "action": "compare", "same_entry": matched}
    return emit(payload, EXIT_OK if matched else EXIT_IO)


def cmd_resolve_vaults(args: argparse.Namespace) -> int:
    try:
        resolved = resolve_vaults(args.config_dir)
    except ItemError as exc:
        return fail(str(exc), EXIT_USAGE)
    return emit({"ok": True, "action": "resolve-vaults", **resolved})


def _memo_inputs(args: argparse.Namespace) -> tuple[str | None, dict[str, Any] | None]:
    item = read_item(args.item) if getattr(args, "item", None) is not None else None
    original = None
    if item is None:
        if getattr(args, "original", None) is not None:
            original = args.original
        elif getattr(args, "original_file", None) is not None:
            original = args.original_file.read_text(encoding="utf-8")
        else:
            raise ItemError("--item, --original, or --original-file is required")
    return original, item


def _parse_link_map(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ItemError("link map must be a JSON object of id to title")
    return {str(key): str(value) for key, value in data.items()}


def _memo_emit(result: dict[str, Any], action: str | None = None) -> int:
    payload = {
        "ok": True,
        "action": action or result["action"],
        "path": result.get("path", ""),
        "relpath": result["relpath"],
        "old_relpath": result.get("old_relpath", ""),
        "id": result["id"],
        "idempotency_key": result["idempotency_key"],
        "source": result["source"],
        "reported_at": result["reported_at"],
        "occurred_at": result.get("occurred_at", ""),
        "title": result["title"],
        "filename": result["filename"],
        "has_body": result["has_body"],
    }
    return emit(payload)


def cmd_plan_memo(args: argparse.Namespace) -> int:
    try:
        original, item = _memo_inputs(args)
        if item is not None:
            fields = item["fields"]
            extras = extra_sections_from_item(item)
            planned = plan_memo(
                item["original"],
                fields["source"],
                fields["reported_at"],
                fields.get("occurred_at", ""),
                extra_related=extras.get("Related", ""),
                id_to_title=_parse_link_map(args.link_map),
                memo_dir=args.memo_dir,
                item_id=fields["id"],
                key=fields["idempotency_key"],
                title=args.title,
            )
        else:
            planned = plan_memo(
                original or "",
                args.source or "",
                args.reported_at or "",
                args.occurred_at or "",
                id_to_title=_parse_link_map(args.link_map),
                memo_dir=args.memo_dir,
                title=args.title,
            )
    except (ItemError, json.JSONDecodeError) as exc:
        return fail(str(exc), EXIT_USAGE)
    planned["path"] = ""
    planned["old_relpath"] = ""
    return _memo_emit(planned, action="planned")


def cmd_write_memo(args: argparse.Namespace) -> int:
    try:
        vault_root = args.vault_root
        if vault_root is None:
            resolved = resolve_vaults(args.config_dir)
            path = resolved.get("default_vault_path")
            if not path:
                raise ItemError("default vault path is not configured")
            vault_root = Path(path)
        original, item = _memo_inputs(args)
        result = write_memo(
            vault_root,
            original=original,
            source=args.source,
            reported_at=args.reported_at,
            occurred_at=args.occurred_at or "",
            item=item,
            memo_dir=args.memo_dir,
            config_dir=args.config_dir,
            id_to_title=_parse_link_map(args.link_map),
            relocate=bool(args.relocate),
            title=args.title,
        )
    except ItemError as exc:
        message = str(exc)
        if "already exists" in message:
            code = EXIT_CONFLICT
        elif "refusing" in message:
            code = EXIT_REFUSED
        elif "destination must be" in message:
            code = EXIT_USAGE
        else:
            code = EXIT_USAGE
        return fail(message, code)
    except json.JSONDecodeError as exc:
        return fail(str(exc), EXIT_USAGE)
    return _memo_emit(result)


def cmd_write_vault_note(args: argparse.Namespace) -> int:
    try:
        dest = safe_dest(args.vault_root, args.dest_relpath)
        if args.body_file is not None:
            body = args.body_file.read_text(encoding="utf-8")
        elif args.item is not None:
            body = render_vault_note(read_item(args.item), mode=args.mode)
        else:
            return fail("--body-file or --item is required", EXIT_USAGE)
        result = write_vault_note(dest, body)
    except ItemError as exc:
        message = str(exc)
        code = EXIT_REFUSED if "refusing" in message or "already exists" in message else EXIT_IO
        if "destination must be" in message:
            code = EXIT_USAGE
        return fail(message, code)
    return emit({"ok": True, **result, "path": result["path"]})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic memo-inbox helpers")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Create or deduplicate an inbox item")
    add_inbox_args(create)
    text = create.add_mutually_exclusive_group(required=True)
    text.add_argument("--original", help="Original memo text")
    text.add_argument("--original-file", type=Path, help="File containing the original memo text")
    create.add_argument("--source", required=True)
    create.add_argument("--reported-at", required=True)
    create.add_argument("--occurred-at", default="")
    create.set_defaults(func=cmd_create)

    append = sub.add_parser("append-correction", help="Append a correction without changing the original")
    add_item_arg(append)
    append_text = append.add_mutually_exclusive_group(required=True)
    append_text.add_argument("--text")
    append_text.add_argument("--text-file", type=Path)
    append.add_argument("--at", required=True, help="ISO-8601 instant for the correction")
    append.set_defaults(func=cmd_append_correction)

    status = sub.add_parser("set-status", help="Update item status (idempotent if unchanged)")
    add_item_arg(status)
    status.add_argument("--status", required=True, choices=STATUSES)
    status.add_argument("--imported-path", default="")
    status.add_argument("--imported-at", default="")
    status.set_defaults(func=cmd_set_status)

    validate = sub.add_parser("validate", help="Validate one item or a whole inbox")
    validate.add_argument("--inbox-root", type=Path)
    validate.add_argument("--item", type=Path)
    validate.set_defaults(func=cmd_validate)

    show = sub.add_parser("show", help="Print a parsed item as JSON")
    add_item_arg(show)
    show.set_defaults(func=cmd_show)

    same = sub.add_parser("same-entry", help="Compare two item files for id, key, and original text")
    same.add_argument("--a", type=Path, required=True)
    same.add_argument("--b", type=Path, required=True)
    same.set_defaults(func=cmd_same_entry)

    vaults = sub.add_parser("resolve-vaults", help="Read local vault paths from a config directory")
    vaults.add_argument("--config-dir", type=Path, default=None)
    vaults.set_defaults(func=cmd_resolve_vaults)

    def add_memo_input_args(parser: argparse.ArgumentParser) -> None:
        memo_text = parser.add_mutually_exclusive_group()
        memo_text.add_argument("--original", help="Original memo text")
        memo_text.add_argument("--original-file", type=Path, help="File containing the original memo text")
        memo_text.add_argument("--item", type=Path, help="Legacy inbox item to copy into the vault")
        parser.add_argument("--source")
        parser.add_argument("--reported-at")
        parser.add_argument("--occurred-at", default="")
        parser.add_argument("--memo-dir", default=MEMO_DIR)
        parser.add_argument("--link-map", help="JSON object mapping leftover inbox ids to titles")
        parser.add_argument("--title", help="Optional short title chosen by the assistant")

    plan = sub.add_parser("plan-memo", help="Preview a casual title, filename, and body without writing")
    add_memo_input_args(plan)
    plan.set_defaults(func=cmd_plan_memo)

    memo = sub.add_parser("write-memo", help="Write a casual memo into the vault 备忘 folder")
    memo.add_argument("--vault-root", type=Path)
    memo.add_argument("--config-dir", type=Path, default=None)
    add_memo_input_args(memo)
    memo.add_argument("--relocate", action="store_true", help="Allow updating the indexed path after a format change")
    memo.set_defaults(func=cmd_write_memo)

    write = sub.add_parser("write-vault-note", help="Write a note and verify the read-back")
    write.add_argument("--vault-root", type=Path, required=True)
    write.add_argument("--dest-relpath", required=True)
    write.add_argument("--item", type=Path)
    write.add_argument("--body-file", type=Path)
    write.add_argument("--mode", choices=("original", "prepared"), default="original")
    write.set_defaults(func=cmd_write_vault_note)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
