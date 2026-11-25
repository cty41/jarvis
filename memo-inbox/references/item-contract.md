# Memo contract

New ordinary memos are stored only in the local default notes library, as
one Markdown file: `备忘/<title>.md`. There is no temporary inbox or queue in
this repository.

This pack does not ship historical inbox items. Storage and path rules are
in [storage-boundary.md](storage-boundary.md). Leftover structured item
files may still exist in a user's older private checkout; the fields below
apply only to those leftovers. Do not add new drop-box files.

## Legacy leftover-item fields

| Field | Required | Rule |
| --- | --- | --- |
| `id` | yes | `YYYYMMDD-` plus the first eight hex digits of `idempotency_key`. The date comes from `reported_at`. The filename must be `<id>.md`. |
| `idempotency_key` | yes | SHA-256 hex digest of `normalize(original) + "\n" + normalize(source)`. |
| `source` | yes | Where the memo came from, such as `user-chat`. |
| `reported_at` | yes | ISO-8601 instant with an explicit offset or `Z`. |
| `occurred_at` | no | When the event happened, if known. Leave empty when unknown. Same timestamp form when present. |
| `status` | yes | One of `pending`, `prepared`, `imported`, `needs-review`. |
| `imported_path` | no | Vault-relative path recorded after a verified local import. Required when `status` is `imported`. |
| `imported_at` | no | Instant of the verified import, when known. |

`normalize` means: unify newlines to `\n`, strip trailing spaces on each line,
and trim leading and trailing whitespace. Do not otherwise rewrite the wording.

## Body

The body has an `## Original` section and an `## Corrections` section.
`## Conflicts` is added only when a same-id collision is recorded.

```markdown
---
id: 20261113-aaaaaaaa
idempotency_key: aaaaaaaa...
source: user-chat
reported_at: 2026-11-13T18:00:00+08:00
occurred_at: ""
status: pending
imported_path: ""
imported_at: ""
---

## Original

周六去图书馆还书

## Corrections
```

The original text is immutable after the first successful write. Later
corrections are appended under `## Corrections` as `### <instant>` blocks.
Do not edit or replace the original section.

## Status

Allowed transitions:

- `pending` → `prepared` | `imported` | `needs-review`
- `prepared` → `pending` | `imported` | `needs-review`
- `needs-review` → `pending` | `prepared` | `imported`
- `imported` → `needs-review`

`pending` is a received item that is not yet in a local notes library.
`prepared` is for a rewrite draft stored under the vault's `ai-review/` folder.
`imported` is only set after a local write and a successful read-back.
`needs-review` is for collisions, uncertain splits, or a failed review.

Repeating the same status is allowed and must not rewrite the vault note.

## Dedup and conflicts

A later message with the same normalized original text and source is the same
item: reuse that `id`, do not create a second file.

If two different payloads would occupy the same `items/<id>.md` file, keep the
existing original, append the incoming text under `## Conflicts`, set
`status` to `needs-review`, and do not drop either version.

## Vault memo (`备忘/<title>.md`)

This is the canonical ordinary-memo file. It is a casual note:

- The filename stem is the title the notes app shows. Do not use a timestamp or technical id as the filename.
- Short memos: after stripping「记一下」and any immediately following punctuation or spaces, the remaining text is the title when it is still short. Do not repeat that text in the body.
- Longer memos, including a long single sentence: prefer an explicit short title from the assistant. If none is given, use a conservative, faithful short title taken from the text. Keep the wording after the trigger as the body. A length fallback of about 30 characters is only a safety net. Do not invent facts.
- On Windows, store ASCII colons in titles as a fullwidth `：`.
- The file is plain Markdown. It must not contain YAML frontmatter or template headings such as `## Original`, `## Corrections`, or `## Related`.
- Leftover related text may be kept as ordinary prose, with wiki links such as `[[title]]` instead of internal ids.

Technical identifiers stay out of the note. The notes machine keeps a lightweight index in the config directory (`memo-index.json`, beside the vault pointers) with only `id`, `idempotency_key`, and `relpath`. The index must not store memo bodies, and it is not an inbox or a second notes library.

A later message with the same normalized original text and source is the same memo only if the indexed file still exists and still matches the planned content. If the destination filename already holds different text, or the indexed file is missing or has been edited, do not overwrite and do not report the memo as already saved.

To compare two copies of a current vault note, use normalized file text (and the filename stem when the body is empty). Do not invent an `id` from the filename. Structured leftover items still compare `id`, idempotency key, and original text.

`pending`, `prepared`, `imported`, and `needs-review` apply only to leftover inbox items, not to new vault memos. After a leftover ordinary item is written to `备忘/<title>.md` and read back, its inbox `status` may be set to `imported` with `imported_path` set to that vault-relative path. Do not automatically migrate other leftover items unless the user asks.

## Helper

Deterministic checks and writes are in
[`../scripts/memo_inbox.py`](../scripts/memo_inbox.py). Use it to write a
memo directly into `备忘/` with a natural title, record a lightweight config-dir index, deduplicate by idempotency key, refuse conflicting overwrites, compare two copies of an entry, resolve local vault paths from config, and (for leftover inbox files only) update import status.
