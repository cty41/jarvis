# Ownership boundary

Kit-owned: `00_System/managed/**` and generated reports.

User-owned: root entry documents, `00_System/local/**`, Projects, Areas, Resources and Archive.

Upgrade stops on managed drift and must never overwrite user-owned content.

Storage commands reject code checkouts and existing symlinks/junctions in storage
paths. Archive accepts project slugs only. Repeated init validates the managed
lock/checksum without overwriting it; missing locks or drift fail closed. Backups
are full plaintext copies to an external, non-code directory, not encryption.
Use a trusted local filesystem and do not replace ancestors during operations;
these checks are not an operating-system sandbox against concurrent hostile
filesystem mutation.
