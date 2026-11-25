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
  only — never memo bodies. It is not an inbox.
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
