---
name: memo-inbox
description: >-
  Use when the user says「记一下」or「归档」and wants a memo stored in the local
  default notes library. Not for reminders, full-chat monitoring, or storing
  medical, identity, credential, account, or third-party intimate information
  in the default library or this repository.
---

# memo-inbox

Store an ordinary memo directly in the local default notes library when the
user asks. These are casual notes: the filename is the title Obsidian shows,
and the file is plain Markdown without YAML frontmatter or template headings
such as `## Original`. The long-term location is the permanent `备忘/` folder
at the root of that library. There is no temporary inbox, no offline queue,
and nothing is written to this repository or to GitHub for a new memo.

## Quick Reference

| Need | Do |
| --- | --- |
| User says「记一下」or「归档」 | Start this skill. Do not scan the rest of the chat for memos. |
| Classify first | Ordinary memos may go to the default library. Medical or family health, identity documents, login credentials, bank or account details, and intimate or sexual details of an identifiable third party must not. |
| Mixed sensitive + ordinary | Block the whole message first. Split out a non-sensitive part only after the user confirms. Default: do not store the whole text. |
| Ordinary memo, notes machine online | Resolve the default library from that machine's config, write `备忘/<title>.md` with machine-targeted tools, read it back, then say「已入库」. |
| Short memo | After stripping「记一下」and following punctuation or spaces, use the remaining text as the filename/title when it is still short. Do not repeat it in the body. |
| Long memo | If the remaining text is too long — a long single sentence or more than one sentence — use a short, faithful title and keep the wording after the trigger as the body. Prefer an explicit `--title` chosen by the assistant. A length fallback of about 30 characters is only a safety net, not a reason to keep a long sentence as the filename. Do not invent facts. |
| Duplicate of an already stored memo | Reuse the same file. Do not add a second file. |
| Same filename, different text | Do not overwrite. Keep the existing file, report a conflict, and leave the new text in the conversation until the user decides. |
| Later addition to a stored memo | Append as ordinary prose. Do not add `## Original` or `## Corrections` headings. |
| Notes machine offline | Leave the text in this conversation and say it is not yet stored. Do not invent a queue, do not write this repository or GitHub, and do not say it was queued. |
| Sensitive, machine offline | Same as above: conversation only, not yet stored. |
| Sensitive, machine online | Write only to the sensitive local library. Never to the default library's `备忘/`, and never to this repository. |
| Confirm「已入库」 | Only after the local file is written and read back successfully. |

| Helper | Command |
| --- | --- |
| Resolve library roots | `python3 scripts/memo_inbox.py resolve-vaults --config-dir <machine-config-dir>` |
| Preview title and body | `python3 scripts/memo_inbox.py plan-memo --original "记一下 周六去图书馆还书" --source user-chat --reported-at <ISO instant>` |
| Write a new memo into `备忘/` | `python3 scripts/memo_inbox.py write-memo --vault-root <library> --config-dir <machine-config-dir> --original "记一下 周六去图书馆还书" --source user-chat --reported-at <ISO instant> [--title "短标题"]` |
| Write from a leftover inbox item | `python3 scripts/memo_inbox.py write-memo --vault-root <library> --config-dir <machine-config-dir> --item <legacy-file>` |
| Compare two copies | `python3 scripts/memo_inbox.py same-entry --a <written> --b <read-back-copy>` |
| Record leftover inbox status (no new inbox items) | `python3 scripts/memo_inbox.py set-status --item <legacy-file> --status imported --imported-path 备忘/<title>.md --imported-at <ISO instant>` |

The default library path comes from `default-vault.json` field `vaultPath` in the notes machine's config directory (default `~/.config/alfred/` for compatibility with existing local pointers; override with `--config-dir` or `MEMO_CONFIG_DIR`). The sensitive library path comes from `records-vault.json` in the same directory. A lightweight index of technical ids, relative paths, and content hashes lives in the same config directory as `memo-index.json`. It has no separate body field, but relative filenames can disclose the full short memo; treat the index as private. It is not an inbox. Read that config on the notes machine; do not assume the current checkout can see it. Do not invent a machine-specific path, and do not put machine paths, the index, or library files in this skill or in git.


Field rules: [references/item-contract.md](references/item-contract.md). Storage boundary: [references/storage-boundary.md](references/storage-boundary.md).

## When to use

- The user explicitly says「记一下」or「归档」and provides (or points to) the text to keep.

Do not use this skill for reminders, calendar alerts, or a request that is only "remind me later". Do not convert a reminder into a memo unless the user also says「记一下」or「归档」. Do not watch the whole conversation or file messages that were not explicitly submitted. Do not use this skill to store medical or family-health notes, identity documents, passwords or other credentials, bank and account data, or intimate or sexual details of an identifiable third party in the default library or in this repository.

Do not write new memos into this skill-pack checkout. This pack does not ship historical inbox items.

## Workflow

### 1. Confirm the trigger and keep the original words

Proceed only when the user has clearly asked to record or file a memo. Copy the original wording. If the occurrence time is stated, keep it as `occurred_at`; if not, leave that field empty. `reported_at` is the time the user submitted the memo, with an explicit timezone offset.

Plain-text memos only. If the user sends an attachment or an image, ask them to paste the text. Do not do OCR in this skill.

### 2. Classify before writing anywhere

Treat a memo as sensitive when it includes any of the following:

- Medical information or a family member's health
- Identity documents
- Login credentials
- Bank cards or account details
- Intimate or sexual details of an identifiable third party

Ordinary examples, safe for the default library, look like「周六去图书馆还书」.

If the same message mixes sensitive and ordinary content, stop and tell the user the whole item is blocked. Do not store it in the default library or this repository. Only after they confirm a split may the non-sensitive part be stored as its own memo. The default is not to store the whole text.

### 3. Store an ordinary memo in the default library

Run this step only when the machine that holds the local libraries is online. Use machine-targeted tools to read the config and to write and read back the note. If the helper cannot see the vault path from the current checkout, render the note with the helper and copy those bytes onto the notes machine, then read that path back.

```bash
python3 scripts/memo_inbox.py resolve-vaults --config-dir ~/.config/alfred
```

- Default library: `~/.config/alfred/default-vault.json` field `vaultPath`
- Sensitive library: `~/.config/alfred/records-vault.json` field `vaultPath`

If a needed path is missing, ask once where the library lives. Ordinary memos go to that library's `备忘/<title>.md`. Prefer passing `--title` when the assistant has a short, faithful title. Otherwise the helper uses the text after「记一下」: if that text is still short, it becomes the filename and is not repeated in the body; if it is too long — including a long single sentence — it gets a conservative short title, and the wording after the trigger is kept as the body. A length fallback of about 30 characters is only a safety net. On Windows, ASCII colons in titles are stored as a fullwidth `：`. Technical ids and hashes are recorded only in `memo-index.json` under the notes machine's config directory, never as visible frontmatter in the note.

```bash
python3 scripts/memo_inbox.py write-memo \
  --vault-root <default-library> \
  --original "周六去图书馆还书" \
  --source user-chat \
  --reported-at 2026-11-13T18:00:00+08:00
```

The command prints JSON. `written` means a new file was stored and read back. `duplicate` means the same memo already exists; keep that file. `conflict` (exit code 3) means the destination already holds different text: do not overwrite, and leave the incoming text in the conversation until the user decides.

Then:

1. Read the same path back from the notes machine and compare it with the text just written. For current `备忘/` notes, `same-entry` compares normalized file text; title-only notes also require the filename stem to match. Treat `duplicate` as already stored only when the file still exists and still matches. A missing or edited target is a failure.
2. Say「已入库」only after that read-back matches. If the machine has not confirmed the file, say so and do not claim it was stored.
3. Never write the note into this skill-pack checkout, and never add library files to git.

If the user later corrects a current `备忘/` note, update that plain library file. Do not introduce YAML frontmatter or `## Original` headings.

### 4. Handle a missing machine or sensitive text

Do not write sensitive or mixed-blocked text into the default library or any path in this skill-pack checkout.

- If the machine that holds the local libraries is **offline**: leave the text in the current conversation. Say clearly that it has not been stored yet. Do not create another store or queue, do not write this repository or GitHub, and do not say the memo was queued successfully.
- If that machine is **online** and the text is sensitive: write only to the sensitive local library, then read the file back. Say「已入库」only after the read-back matches. Record nothing in git.

### 5. Leftover structured items

This pack does not ship historical inbox items. If a user already has leftover structured drop-box files from an older workflow, do not add new ones, and do not delete them unless the user explicitly asks. After a leftover ordinary item has been written to `备忘/` and read back, its frontmatter may be updated to `imported` with `imported_path` set to the vault-relative `备忘/<title>.md`. Do not commit or push that status change unless the user explicitly asks.

Do not run a general migration of leftover items unless the user asks to move specific ones.

### 6. What this skill does not do

It does not install a notes-library server or third-party plugin. It does not set up a scheduled import, a routine, or a local scheduled task. It does not create a temporary inbox or offline queue. It does not clean git history. It does not handle attachments or OCR.

## Anti-patterns

| Wrong | Right |
| --- | --- |
| File a chat message that was never submitted with「记一下」or「归档」 | Wait for an explicit ask |
| Turn a reminder into a memo automatically | Leave reminders as reminders |
| Put medical, credential, account, or third-party intimate text in `备忘/` or this repository | Keep those out of the default library and out of the repository |
| Upload or store a mixed message and hope to redact later | Block the whole item until the user confirms a split |
| Write a new memo into this checkout or GitHub so it can be imported later | Write it directly to the default library, or leave it in the conversation if the machine is offline |
| Say the memo was queued while the notes machine is offline | Say it is only in this conversation and not yet stored |
| Create a second offline store or a scheduled catch-up task | Do not. There is no intermediate queue |
| Say「已入库」before the library file is read back | Read the same path back from the notes machine first |
| Put YAML frontmatter, timestamp filenames, or `## Original` / `## Corrections` in a casual memo | Use a natural title as the filename and plain prose in the body when needed |
| Overwrite an existing `备忘/<title>.md` that has different text | Keep the existing file and report a conflict |
| Hard-code a machine path in the skill or a commit | Read library roots from the notes machine's `~/.config/alfred/` or ask once |
| Add library files to git, or use this checkout as a notes library | Never. Vault files stay only on the notes machine |

## Checklist

- [ ] The user explicitly said「记一下」or「归档」.
- [ ] Sensitive, mixed, and ordinary text were classified before any write.
- [ ] Ordinary memos were written to the default library as `备忘/<title>.md`, with a natural title, no visible frontmatter, and no template headings.
- [ ] A stored memo was confirmed by reading the same path back from the notes machine before saying「已入库」.
- [ ] Duplicates reused the same file; conflicts did not overwrite an existing note.
- [ ] Sensitive text never entered the default library or this repository. If the notes machine was offline, the user was told the text is not yet stored.
- [ ] No new file was written under this skill-pack checkout. No temporary queue, routine, or scheduled task was created.
- [ ] Vault files were not added to git.

## Local storage safety

The library root must already exist and be available. Missing roots fail; the
helper does not create a replacement library or an offline queue. Code repositories,
skill-pack roots, and existing symlinks/junctions in storage paths are refused for
notes and indexes. A normal local directory (not a hostile shared filesystem) is
required; do not move or replace its ancestors while writing.

The index has no separate body field, but `relpath` contains the natural title,
which can be the entire short memo. JSON output also contains titles and paths.
Treat the index and captured output/logs as private, just like notes; never commit
or upload them. A lock serializes helper writes; a stale lock fails closed and
needs review, never an automatic queue/retry job. If an I/O error follows a note
write, the note may exist without its index entry: verify before retrying.
The legacy `create` command is disabled. Only existing leftover files may be
updated after explicit user authorization; new memos always go directly to the
configured library and need successful read-back before confirmation.

The config directory also holds `memo-vault-identity.json`, pinning directory
device/inode identity on first use of an already-existing root. A later mount or
directory replacement fails until explicitly reviewed; never auto-rebind it.
First-use identity cannot prove that an arbitrary existing directory is the
intended mounted library: verify the configured location before first use.
