# AList API and safety reference

Read this reference before connecting to an unfamiliar AList instance or executing a plan.

## Environment variables

```text
ALIST_URL                 Required. Example: http://192.168.1.20:5244
ALIST_TOKEN               Preferred short-lived AList token
ALIST_TOKEN_FILE          Alternative mode-0600 file containing one short-lived token
ALIST_USERNAME            Alternative login username
ALIST_PASSWORD            Alternative login password
```

Set only one of `ALIST_TOKEN` or `ALIST_TOKEN_FILE`. Never place tokens or passwords in command arguments, plan files, journals, screenshots, or social posts. Plain `http://` exposes credentials and tokens to anyone able to intercept the network; use HTTPS where practical.

## Connection chain

```text
Skill script
  -> AList HTTP API
     -> writable AList storage driver
        -> provider-side in-place rename or exact folder move
           -> VidHub file-source rescan
              -> VidHub/TMDB metadata match
```

Connect safely:

1. Confirm `GET /api/public/settings` reaches the intended AList instance and record the version.
2. In AList, create a temporary user for the canary. Set its base path to the parent of the test directory and grant only the permissions needed to browse/list, rename, create a directory, and move within that base path. Do not use the built-in admin account.
3. Ensure the test directory is a non-root path from that user's view, for example `/Canary`. The script refuses mutation against `/`.
4. Run `login` interactively in the user's own terminal. It prompts for the password and creates a new token file with mode `0600`:

   ```bash
   export ALIST_URL='https://alist.example.test'
   export ALIST_USERNAME='codex-canary'
   python3 scripts/alist_vidhub_namer.py login --token-file work/alist-canary.token
   export ALIST_TOKEN_FILE="$PWD/work/alist-canary.token"
   ```

5. Run `check`, then `plan`; both are read-only. Confirm `write: true`. The provider name is diagnostic only; do not infer its rename, mkdir, or move support from the name.
6. After the user approves the exact root and every mapping, execute the canary plan with `--confirm-video-count` set to the batch size.
7. Verify every item in AList and VidHub. Delete the local token file and disable the temporary user or revoke its session.

AList documents that a login token is temporary and defaults to 48 hours. Treat it as a secret for its entire lifetime.

## Endpoints used

The bundled script uses only:

- `GET /api/public/settings`
- `POST /api/auth/login`
- `POST /api/fs/list`
- `POST /api/fs/rename`
- `POST /api/fs/mkdir` with exactly `{"path": "/absolute/direct-child"}`
- `POST /api/fs/move` with exactly `{"src_dir": "...", "dst_dir": "...", "names": ["one name"]}`

It never calls delete, recursive-move, copy, upload, storage-admin, or direct cloud-provider APIs. `mkdir` and `move` are available only through the dedicated 1-20-folder organization plan, and every move request contains exactly one planned name.

The optional processing ledger is a local mode-0600 SQLite file. State initialization, status, and journal rebuild make no AList or TMDB calls. `pending-report` uses the same read-only AList listing contract as `plan`; it does not mutate remote state. Do not place a user's ledger in the shared Skill archive because it contains paths and processing history.

The Skill can optionally call three read-only TMDB endpoints through the deterministic BYOK client documented in `tmdb-api.md`. Each user supplies their own credential after reviewing the current terms. The client stores only minimal candidates, never bypasses user confirmation, and never sends the credential to AList or VidHub. VidHub still performs the final metadata lookup under its own integration.

Official API documentation:

- Authentication: https://alistgo.com/zh/guide/api/auth
- List and rename: https://alistgo.com/zh/guide/api/fs.html
- User permissions: https://alistgo.com/zh/guide/advanced/user.html

## Storage-driver constraints

- AList drivers vary. Confirm `write: true`, but still treat a failed preflight or mutation endpoint as a hard stop; do not retry with a broader operation.
- The Skill never uses copy, even if a mounted driver supports it. It uses only in-place renames and same-storage folder moves.
- Keep execution single-threaded and delayed. Remote storage APIs can rate-limit or temporarily return stale directory data.
- Consult the AList documentation for the user's specific mounted storage driver before expanding beyond a canary.

## Mutation protocol

1. Scan and write a local plan. Make no remote changes.
2. Review every `review` and `conflict` entry. Only `ready` entries at or above the threshold are executable.
   Use the local `approve` command for identities the user has verified; it changes only a copy of the plan and performs no API calls.
3. For a canary, use `select` to create a plan with exact video paths. It accepts at most 20 videos and includes clearly paired subtitles.
4. Re-list every affected directory immediately before execution.
5. Stage selected files to unique temporary names, then rename them to final names. This prevents swaps and rename cycles from overwriting one another.
6. Persist a journal after every successful remote mutation.
7. On failure, attempt to restore original names immediately. If the journal says `manual_recovery_required`, stop and inspect it; do not retry with broader operations.
8. Before rollback, validate every journal directory and derived old, temporary, target, and restore path against the confirmed root. Reject a damaged or edited journal before any API call or journal status change.
9. Keep the journal until Infuse or VidHub has rescanned successfully. Use the rollback command if needed.

For folder renames, require a separate `folder-plan` containing 1-20 exact direct children of a narrow parent path. Confirm the folder count independently with `--confirm-folder-count`. Keep folder and video journals separate. If both layers must be undone, restore folder names before using a video journal whose recorded paths are inside those folders.

For the complete `Movies/` or `TV Shows/` layer, require a separate `organize-plan` containing 1-20 exact source folders and one safe destination. Sources and the destination are relative to the plan root: a bare name is a direct child, and a value with `/` addresses a folder nested under the root at any depth. Every segment is validated like a direct-child name; `.`, `..`, and absolute values are refused, so no resolved path escapes the root. The plan also refuses two sources where one contains the other. Confirm the resolved absolute paths, not the relative arguments. `organize-apply` re-lists both sides, creates the destination if absent, then calls the single-name move contract sequentially. It writes a journal after every successful mutation and automatically reverse-moves completed items after a failure. `organize-rollback` validates all derived paths before any API call or journal update, checks occupancy, and moves folders back one at a time. It does not delete the destination; if this run created it, rollback leaves the empty folder and records that fact.

When video names, media folders, and organization have all changed, roll back in reverse dependency order: organization move, media-folder rename, video rename.

After renaming, rescan only the changed Infuse or VidHub file source or directory. A full library scan can be expensive for large libraries.

## Batch auto-execute mode

See SKILL.md's "Batch auto-execute mode (opt-in)" for the full rule. Summary: once a user opts in for a session, **video-name** executions for unambiguous entries proceed without a separate per-item confirmation. Unambiguous means `tmdb_resolution.status` is `proposed` (the resolver's own four-part gate — exact title, exact year, score at least 0.9, and a 0.1 lead), plus no destination conflict and a live folder layout matching the plan's scope. Do not re-derive that gate from raw scores.

Folder-name renames and `organize-apply --execute` moves stay batch-confirmed even in this mode: both rewrite paths that earlier journals reference, so they share one explicit per-batch confirmation covering every folder pending a rename or move at once.

Because `approve` stamps `manually_verified`, confidence 1.0, and a `verification_note` that propagate into the journal and ledger, any `approve` run by batch mode must pass an explicit `--note` marking it auto-approved and unreviewed. Leaving the default `verified by user` text makes auto-approved and human-verified entries indistinguishable in the audit trail.
