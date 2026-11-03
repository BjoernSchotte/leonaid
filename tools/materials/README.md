# Cleaning up an abandoned material upload

An interrupted upload can leave a private object-storage version without a
`material_version` row. Repeating the same upload command adopts it. Only when
the retry is given up for good does `leonaid.entrypoints.material_cleanup`
remove one exactly identified version. There is no bucket scan and no
automatic deletion by file age.

Before you start: every API and worker instance must run a release with the
upload lock; stop older processes first. The cleanup uses the same core
database and object-storage configuration as the application and only
considers material objects of the configured bucket, never survey or invoice
files.

1. In the administrative object-storage version view, find the exact key
   `materials/<material-uuid>/<upload-uuid>` and the exact storage version ID.
   Do not use the business version number. Never delete a whole material
   prefix.
2. Check first, with a currently active system administrator account and a
   traceable reason. The normal runtime configuration, secrets included, must
   be in the process environment; never put secrets on the command line or in
   Git:

   ```sh
   docker compose exec api python -m leonaid.entrypoints.material_cleanup \
     --actor "$ADMIN_USER_ID" \
     --material "$MATERIAL_ID" \
     --upload "$UPLOAD_ID" \
     --storage-version "$STORAGE_VERSION_ID" \
     --reason 'Upload abandoned for good, case checked'
   ```

3. `would-delete` means the version is unreferenced now and confirmed as a
   material object. Repeat the same call with `--apply` to delete it. The check
   runs again; it does not reuse the earlier result. `already-absent` is a
   successful result when you repeat a call.

The uploader and the cleanup hold the same PostgreSQL transaction lock per
bucket and object key. A running upload is waited for: after its commit, its
reference prevents the deletion; after a rollback, the orphaned version can be
removed. The deletion touches only the given storage version and then checks
that it is gone. Referenced versions are refused with
`material_upload_referenced`.

Before an actual deletion, `material.upload_cleanup_requested` is audited with
the selectors and the reason; `material.upload_cleanup_completed` confirms the
finished attempt, both with the same request ID. A requested attempt without a
completion may have been refused or interrupted and needs a check. After a
storage error or a crash, repeat the exact same call: it checks database and
storage again. A later retry of the original upload can store the removed bytes
again; existing stored file versions stay unchanged.

After a restore, the existing restore and restart rules apply. Never run the
cleanup against an incomplete or just restored database: only the
authoritative, fully restored database can confirm references.

Proof: `tools/materials/cleanup_contract.py` uses real PostgreSQL
transactions, competing locks, RustFS versions and the actual CLI process. The
contract runs in the schema gate.
