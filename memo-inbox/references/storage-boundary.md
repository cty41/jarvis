# Memo storage boundary

This skill records ordinary memos only in a local notes library chosen on
the notes machine. It does not ship historical inbox items, personal notes,
or library path defaults that point at a specific person's disk.

## Where notes may be written

- Ordinary, non-sensitive memos that the user explicitly asked to record go
  to `<default-library>/备忘/<title>.md`.
- The default library path is read from the notes machine's config directory:
  `default-vault.json` field `vaultPath`. The default config directory is
  `~/.config/alfred/` for compatibility with existing local pointers; override
  it with `--config-dir`, or with `MEMO_CONFIG_DIR` / `JARVIS_CONFIG_DIR`.
- A lightweight index (`memo-index.json`) may live in that same config
  directory. It stores technical ids, relative paths, and content hashes
  without a separate body field. Filenames can still disclose memo wording; treat
  this index as private. It is not an inbox.
- Sensitive text belongs only in a separate sensitive library, if the user
  has one configured (`records-vault.json` in the same config directory).
  Do not write sensitive or mixed-blocked text to the default library.

## Where notes must not be written

- Do not write memos into this skill-pack checkout, including any copy or
  link of it, whether or not an `inbox/` directory exists.
- Do not write memos into git, GitHub, or any other code repository.
- Do not create a temporary inbox, offline queue, or scheduled import.
- If the notes machine is offline or the library path is missing, leave the
  text in the current conversation and say it has not been stored yet.

## Confirming a write

A `duplicate` result is valid only when the indexed file still exists and
its content still matches the planned memo. A missing or edited target is a
failure, not a successful store.

After a write, read the same path back from the notes machine:

- Current `备忘/` notes are plain Markdown. Compare normalized file text. If
  the body is non-empty, matching content is enough even when a read-back
  copy lives at another path. Title-only (empty-body) notes also require the
  filename stem to match, because the title is the identity.
- Leftover structured items, if a user still has them, compare `id`,
  idempotency key, and original text.
- Say「已入库」only after that read-back matches.

Legacy inbox helpers in the script remain only so a user who already has
historical drop-box files can update their status after a verified write.
This pack does not include those files and does not import them automatically.

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
