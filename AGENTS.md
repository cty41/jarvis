# Jarvis — authoring rules

Jarvis is a general-purpose, user-level, cross-project skill pack. It contains
reusable methods only. Personal notes, health records, and machine-specific
paths stay in the user's local libraries, never in this repository.

## First, decide which kind of request this is

- **Using Jarvis skills:** the skills are installed in a user or project skill
  root and are triggered by their own `description`. Do not restate trigger
  conditions here. For installing or updating, follow [README.md](README.md).
- **Changing Jarvis itself** (adding, editing, or removing skills, the
  installer, or scripts): follow the rules below and run `scripts/validate.ps1`
  when done.
- **Working with ordinary memos** the user explicitly asked to record
  (「记一下」or「归档」): write only to the local default notes library, using
  `memo-inbox`. Do not write memos into this checkout or to git.
- **Working with a personal knowledge vault:** use `life-knowledge` against a
  user-specified local vault path or local profile. Do not copy vault content
  into this repository.
- **Health, mood screening, or illness-tracking requests:** those methods are
  not part of this pack. Do not add personal health data here.

Do not commit or push unless the user asks explicitly, and do not touch
untracked files in this checkout that are unrelated to the skill pack.

## Non-negotiable

1. **Flat only.** A skill is `<skill-name>/SKILL.md` at the repository root.
   Nested skill groups (e.g. `prod/grill-me/SKILL.md`) are invisible to standard
   discoverers (Cursor, Codex, Claude Code, and other Agent Skills hosts) and
   are rejected by the nesting audit in `scripts/validate.ps1`.
2. **Portable frontmatter.** `SKILL.md` frontmatter contains exactly `name` and
   `description`. No tool-specific fields (`allowed-tools`, `argument-hint`,
   `tools`, …). Tool limits belong in the body. This is a conservative profile
   for portability; it does not claim that the Agent Skills standard forbids
   additional fields.
3. **Progressive disclosure.** Every skill provides, in order:
   Quick Reference → When to use → Workflow → Anti-patterns (recommended) →
   Checklist (recommended). Long templates, formal contracts, and examples go
   in `references/` and are read when needed.
4. **No project-specific or personal content.** No mention of a particular
   person's machine paths, family or health facts, or a private repository
   address. Project conventions are parameterized in the skill body or mapped
   by the project's own `AGENTS.md`.
5. **Nothing sensitive.** No tokens, personal data, credentials, or
   machine-specific usernames.
6. **Scripts live with their skill.** Deterministic, error-prone steps belong in
   scripts inside the skill's own directory (`<skill>/scripts/` or a bundled
   kit), referenced relative to the skill. Judgment stays in `SKILL.md`. Every
   bundled script ships with tests that `scripts/validate.ps1` runs.
   `knowledge-maintenance` is the exception that uses repo-root
   `tools/okf-lite/`; install or copy that closure with the skill.
7. **Rules are templates.** Portable rules live in `rules/` and are not
   installed; projects copy them into their own `.agents/rules/`. A skill that
   refers to a rule uses a relative path.
8. **No reverse private dependency.** Jarvis must not depend on a private
   skill pack, private repository URL, or implicit checkout of one.

## Gate

`scripts/validate.ps1` must be green before any push:

- `quick_validate` per skill when the skill-creator validator is installed
  (`~/.codex/skills/.system/skill-creator/scripts/quick_validate.py`);
- nesting audit (no `SKILL.md` deeper than `<root>/<skill-name>/`);
- local relative markdown links resolve;
- installer tests, OKF-lite unit tests, and bundled Pester suites pass.

In a checkout where the pack is installed, `scripts/smoke.ps1` should also be
green — the source of truth always, the links only after installation. Default
smoke checks the 12 default skills; pass `-IncludeCompat` after a compat
install.

## Versioning

Rolling updates; tag releases only when a stable cut is needed. Update
consumers by pulling this repository and re-running `scripts/install-user.ps1`
(add `-IncludeCompat` if aliases were previously opted in).

## Attribution

Some skills were originally ported from a personal `tactics` repository (MIT).
Do not remove the attribution note in `README.md`. Third-party material must
keep its own NOTICE entry in `THIRD_PARTY_NOTICES.md`.
