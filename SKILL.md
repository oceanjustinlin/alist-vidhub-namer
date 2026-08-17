---
name: alist-vidhub-namer
description: Safely connect, scan, match, normalize, organize, rename, track processed state, and roll back movie, TV episode, special, subtitle, and media folder layouts on AList for Infuse and VidHub scraping. Use when working with any writable AList-mounted media library to create a least-privilege connection, resolve candidates with each user's own TMDB token, run exact 1-20 item canaries, create Movies/TV Shows layouts and compatible names, filter mixed folders through a version-aware local SQLite ledger, apply approved mkdir/move/rename operations through fixed AList API contracts, rebuild state from journals, or undo changes.
---

# AList Infuse + VidHub Namer

Create a reviewable filename plan, then apply only explicitly approved, high-confidence in-place renames. Never download media or call cloud-provider APIs directly.

## Safety invariants

- Default to planning. Do not execute remote renames without the user's explicit approval of the exact AList root path and plan summary, unless the user has opted into batch auto-execute mode (see Workflow), which covers video-name renames only; folder-name renames and the `organize-apply` move into `Movies/`/`TV Shows/` still require one explicit per-batch approval even in that mode.
- Refuse to execute against `/`. Ask the user for a narrower mounted path.
- Never call delete, copy, upload, recursive-move, or AList storage-admin endpoints. Allow `mkdir` and single-name `move` only for an exact 1-20-folder `organize-plan` approved with root and count confirmations.
- Never expose passwords or tokens. Persist AList or user-owned TMDB tokens only through the explicit interactive setup commands; require new mode-0600 files and exclude them from shared artifacts.
- Stop on read-only paths, stale source names, target conflicts, authentication errors, or a journal marked `manual_recovery_required`.
- Keep execution single-threaded. Preserve the journal until VidHub has rescanned successfully.
- Keep user-specific state databases and journals outside the shared Skill. They contain paths and history even though they contain no credentials.

## Workflow

### 1. Establish scope and capability

Read [references/api-and-safety.md](references/api-and-safety.md) before connecting to a new AList instance.

Require:

- an absolute `ALIST_URL`;
- a narrow absolute AList media path;
- `ALIST_TOKEN`, a mode-0600 `ALIST_TOKEN_FILE`, or `ALIST_USERNAME` plus `ALIST_PASSWORD`;

Prefer a temporary least-privilege AList user whose base path is the parent of the intended test root and whose permissions include only the access required to list, rename, create a directory, and move within that root. The target must appear to that user as a non-root path such as `/Canary`, because execution against `/` is refused. Warn before sending credentials over plain HTTP outside localhost.

For a user-run interactive login that avoids putting a password in chat, command history, or process arguments:

```bash
export ALIST_URL='https://alist.example.test'
export ALIST_USERNAME='codex-canary'
python3 scripts/alist_vidhub_namer.py login --token-file work/alist-canary.token
export ALIST_TOKEN_FILE="$PWD/work/alist-canary.token"
```

The token file must be new and readable only by its owner. Delete it and disable or revoke the temporary user after verification. Read [references/api-and-safety.md](references/api-and-safety.md) for the complete connection chain.

Run:

```bash
python3 scripts/alist_vidhub_namer.py check --path '/MediaLibrary/Movies'
```

Report the AList version, provider, and `write` status. Treat the provider name as informational; if `write` is false, stop before planning execution. Do not infer rename, mkdir, or move support from a provider name—preflight and endpoint responses decide whether the plan can proceed.

### 2. Create a dry-run plan

Read [references/naming.md](references/naming.md). For Chinese usage examples, read [references/usage-zh-CN.md](references/usage-zh-CN.md).

For fast candidate lookup, read [references/tmdb-api.md](references/tmdb-api.md). Prefer BYOK when the user has explicitly opted in and accepted the current TMDB terms. Each user must register their own credential; never share the Skill author's token. Run setup in the user's terminal:

```bash
python3 scripts/alist_vidhub_namer.py tmdb-setup \
  --token-file work/tmdb.token \
  --accept-terms
export TMDB_TOKEN_FILE="$PWD/work/tmdb.token"
python3 scripts/alist_vidhub_namer.py tmdb-check
```

Once a TV series ID is verified, also fetch that series' `en-US` episode titles for every season in the batch, through the season endpoint in the same fixed contract. The episode title is a required filename field; see [references/naming.md](references/naming.md).

With a configured token, `plan` defaults to `--resolver auto` and queries TMDB through the fixed local contract. Without one, it falls back to local filename parsing. Use `--resolver none` to prohibit TMDB network access or `--resolver tmdb` to require it.

For a mixed directory, read [references/state-ledger.md](references/state-ledger.md) and run `pending-report` before a full TMDB-assisted plan. It uses the local ledger to exclude files already processed under the current component rule version:

```bash
python3 scripts/alist_vidhub_namer.py pending-report \
  --path '/MediaLibrary/Movies' \
  --resolver none \
  --output work/pending.json \
  --csv work/pending.csv
```

Treat the ledger as a derived index and journals as immutable audit/recovery truth. A Skill release bump alone never invalidates processed files. Only a relevant movie, TV, subtitle, folder, or layout rule-version change produces `needs_recheck`. Never use TMDB ID as a file identity because multiple legitimate releases can share one work ID.

Resolve the second-level folder display mode before presenting folder organization:

- Honor an explicit user choice first.
- For a predominantly Chinese query, default to `localized + canonical`: `中文名 Canonical Title (Year) {tmdb-ID}`.
- For a predominantly English query, default to `canonical only`: `Canonical Title (Year) {tmdb-ID}`.
- For mixed or unclear queries, use the dominant query language and state the assumed mode.
- Show the selected mode in the plan summary and let the user override it. Do not block planning if the user does not respond; use the language-based default.
- Do not duplicate a title when localized and canonical titles normalize to the same text. If a localized title is not verified, use canonical-only and leave the folder label for review.

This choice affects only the media folder directly below `Movies/` or `TV Shows/`. It never changes the canonical identity fields in video filenames. Keep folder mutation in a separate exact-path plan and journal; never mix it into a video canary.

For the complete standard, create the media-type layer first:

```text
<approved root>/
  Movies/
    [中文名 ]Canonical Title (Year) {tmdb-ID}/
      Canonical.Title.Year.{tmdb-ID}.technical-tags.ext
  TV Shows/
    [中文名 ]Canonical Series (First Air Year) {tmdb-ID}/
      Season 01/
        Canonical.Series.S01E01.technical-tags.ext
```

Use a separate organization plan for 1-20 exact source folders. Each `--folder` and the `--destination` is a path relative to `--path`: a bare name is a direct child, and a value containing `/` addresses a folder nested under the root at any depth. Every segment is validated like a direct-child name, and `.`, `..`, and absolute values are refused, so a resolved path can never escape the root. Nesting widens what a single plan can reach, so state the fully resolved source and destination paths — not the relative values you typed — when you present the plan for confirmation. The destination is normally a safe child such as `Movies` or `TV Shows`:

```bash
python3 scripts/alist_vidhub_namer.py organize-plan \
  --path '/MediaLibrary/Incoming' \
  --destination 'Movies' \
  --folder '盗梦空间 Inception (2010) {tmdb-27205}' \
  --output work/movies-organize-plan.json

python3 scripts/alist_vidhub_namer.py organize-apply \
  --plan work/movies-organize-plan.json
```

After the user confirms the exact root, destination, mappings, and folder count:

```bash
python3 scripts/alist_vidhub_namer.py organize-apply \
  --plan work/movies-organize-plan.json \
  --journal work/movies-organize-journal.json \
  --execute \
  --confirm-root '/MediaLibrary/Incoming' \
  --confirm-folder-count 1
```

The script creates the destination only when absent, moves one folder per API call, and journals each move. Its rollback moves folders back but intentionally retains an empty destination created by the run because the Skill never uses delete endpoints.

Create a local JSON list containing 1-20 confirmed direct-child mappings:

```json
[
  {
    "old_name": "Inception_2010",
    "new_name": "盗梦空间 Inception (2010) {tmdb-27205}"
  }
]
```

Create and preview the read-only folder plan:

```bash
python3 scripts/alist_vidhub_namer.py folder-plan \
  --path '/MediaLibrary/Movies' \
  --mapping-file work/folder-mapping.json \
  --output work/folder-plan.json

python3 scripts/alist_vidhub_namer.py apply --plan work/folder-plan.json
```

Require confirmation of the exact parent path, every mapping, and folder count. Batch auto-execute mode does not waive this; it only folds it into the single combined per-batch confirmation. Execute with a separate journal:

```bash
python3 scripts/alist_vidhub_namer.py apply \
  --plan work/folder-plan.json \
  --journal work/folder-rename-journal.json \
  --execute \
  --confirm-root '/MediaLibrary/Movies' \
  --confirm-folder-count 1
```

If both video and parent-folder renames were applied, roll back the folder journal first, then the video journal. Renaming a folder changes every descendant AList path even though the media content is not moved.

If organization was also applied, the full reverse order is: `organize-rollback` first, folder-name `rollback` second, then video-name `rollback`. This restores the parent paths expected by the older journals.

Use `--kind auto` for mixed libraries, or constrain known movie/TV folders.

Write plans and review sheets outside the skill directory:

```bash
python3 scripts/alist_vidhub_namer.py plan \
  --path '/MediaLibrary/Movies' \
  --kind auto \
  --output work/vidhub-plan.json \
  --csv work/vidhub-plan.csv
```

Interpret statuses:

- `ready`: executable only at or above the plan threshold;
- `review`: ambiguous, incomplete, or inferred from a folder name;
- `conflict`: duplicate or occupied target; never execute;
- `skip`: already compliant.

Treat the output as a review surface, not metadata truth. TMDB candidates include a suggested filename, ID, score, and direct URL; show them to the user. Even exact API candidates remain `review` until the user confirms the mapping. Do not invent titles, years, seasons, episodes, or IDs. If an existing plan needs candidates, run `tmdb-resolve` to create a new local plan; never hand-construct requests or write credentials into the plan.

Promote a verified video through the supported local review command; do not hand-edit confidence fields:

```bash
python3 scripts/alist_vidhub_namer.py approve \
  --plan work/vidhub-plan.json \
  --old-path '/MediaLibrary/Movies/Inception_2010_1080p.mkv' \
  --new-name 'Inception.2010.{tmdb-27205}.1080p.mkv' \
  --tmdb-id 27205 \
  --note 'title, year, and movie ID manually verified' \
  --output work/vidhub-plan.approved.json
```

The command preserves extensions, rejects unsafe targets, records a manually verified TMDB mapping, marks the video as manually verified, and updates clearly paired subtitle targets. A movie `--tmdb-id` must also appear in the target filename as `{tmdb-ID}`. For TV, record the series ID with `--tmdb-id` but normally keep it out of episode filenames. For multiple approvals, use the approved plan as both `--plan` and `--output` on later calls.

For a canary, create a second plan containing 1-20 exact ready videos. Repeat `--old-path` once per video; paired subtitles are included automatically:

```bash
python3 scripts/alist_vidhub_namer.py select \
  --plan work/vidhub-plan.approved.json \
  --old-path '/Canary/Movie-A.mkv' \
  --old-path '/Canary/Movie-B.mkv' \
  --old-path '/Canary/Movie-C.mkv' \
  --old-path '/Canary/Movie-D.mkv' \
  --old-path '/Canary/Movie-E.mkv' \
  --expected-videos 5 \
  --output work/vidhub-canary-5.json
```

Never select arbitrary first results. Show every exact mapping in the batch to the user.

### Batch auto-execute mode (opt-in)

By default, follow the full review-then-approve flow in every step below for every mutation. A user running personal, repeated batches over the same library may instead opt into batch auto-execute mode, which changes how much gets confirmed per item versus per batch:

- Ask once, the first time in a session, whether to switch into this mode. Once the user agrees, do not ask again to re-enter it for later batches in the same session.
- Under this mode, resolve TMDB identity, `approve`, `select`, and execute **video-name** renames without a separate per-item confirmation, but only when the item is unambiguous by all of:
  - `tmdb_resolution.status` is `proposed`. Do not restate or re-derive that gate here: `resolve_tmdb_entries` grants `proposed` only for an exact title match, an exact year match, a top score of at least 0.9, and at least a 0.1 lead over the runner-up, all four together. An `ambiguous`, `not_found`, or `unresolved` entry is never eligible, and neither is a lone candidate that failed the gate.
  - No existing folder or TMDB ID conflict already present in the destination directory.
  - The live folder layout matches what the plan expected (flat episodes, or season subfolders whose contents already match the `SxxEyy` filenames). A folder whose actual scope differs from what was scanned or shortlisted — more seasons nested inside than expected, an unexpected wrapper directory — is never unambiguous, regardless of TMDB score; stop and ask how to handle it.
- `approve` stamps `manually_verified`, `confidence` 1.0, and a `verification_note` on the entry, and that provenance is carried into the plan, the journal, and the ledger. When batch mode drives `approve` without a human identity call, always pass an explicit `--note` that says so, for example `--note 'auto-approved in batch mode: tmdb_resolution=proposed, not human-reviewed'`. Never let it fall back to the default `verified by user` text, and never present an auto-approved entry to the user later as if a person had checked it.
- Two mutation classes stay batch-confirmed rather than per-item automatic, because each one invalidates paths that earlier journals depend on:
  - Folder-name renames (`folder-plan` plus `apply`). A folder rename rewrites every descendant AList path, so a wrong target name breaks the paths recorded in every video journal written before it and makes the documented rollback order load-bearing rather than advisory.
  - `organize-apply --execute` moves into `Movies/`/`TV Shows/`.
  Collect one explicit confirmation per batch covering both classes together: present every folder pending a rename or a move across the whole batch at once and get a single combined go, rather than asking per show. Video-name renames for entries that passed the unambiguous test above do not need to wait for it.
- Anything that fails the unambiguous test above still needs the user's identity call before `approve`, exactly as in the default flow — batch mode only removes the *redundant* re-confirmations, not judgment calls a script cannot make.

### 3. Review with the user

Summarize counts by status and media type. Show representative old-to-new mappings and every conflict class. For large plans, give the CSV as the review surface.

Run an apply preview:

```bash
python3 scripts/alist_vidhub_namer.py apply --plan work/vidhub-canary-5.json
```

Ask the user to approve the exact root path, every video mapping in the batch, and total file mutations including subtitles. A request to research, scan, audit, or plan is not approval to rename. Under batch auto-execute mode, video-name mappings that pass the unambiguous test replace this per-mapping approval; folder renames and organization moves still need the one combined per-batch confirmation described there.

### 4. Apply the approved plan

Only after explicit approval — or, under batch auto-execute mode, for video-name entries that passed the unambiguous test — run:

```bash
python3 scripts/alist_vidhub_namer.py apply \
  --plan work/vidhub-canary-5.json \
  --journal work/vidhub-rename-journal.json \
  --execute \
  --confirm-root '/Canary' \
  --confirm-video-count 5
```

The script re-lists affected directories, stages unique temporary names, applies final names, rate-limits operations, and journals every successful mutation. If automatic restoration fails, stop and report the exact journal status.

Successful CLI executions also update `work/alist-vidhub-state.sqlite` by default. Pass the same `--state-db` to apply and rollback commands when overriding it. If the state update warns after a successful remote mutation, preserve the journal and rebuild a new ledger from exact journals; do not repeat the remote mutation.

### 5. Verify and rescan

Create a fresh plan or list the changed directories to verify that targets exist and temporary names do not remain. Then tell the user to rescan only the changed VidHub file source or folder and verify every match in the batch before expanding further. Avoid a full-library rescan for a large collection.

### 6. Roll back when requested

Preview first:

```bash
python3 scripts/alist_vidhub_namer.py rollback --journal work/vidhub-rename-journal.json
```

After explicit approval:

```bash
python3 scripts/alist_vidhub_namer.py rollback \
  --journal work/vidhub-rename-journal.json \
  --execute \
  --confirm-root '/Canary'
```

Do not retry a partial rollback blindly. Inspect name occupancy and journal errors first.

For a Movies/TV Shows organization journal, use the dedicated command:

```bash
python3 scripts/alist_vidhub_namer.py organize-rollback \
  --journal work/movies-organize-journal.json

python3 scripts/alist_vidhub_namer.py organize-rollback \
  --journal work/movies-organize-journal.json \
  --execute \
  --confirm-root '/MediaLibrary/Incoming'
```

## Implementation notes

- Use the bundled Python script; do not reimplement AList mutation calls ad hoc.
- Use only the bundled TMDB client and fixed read-only contract. Never share a credential or send it to any host except `api.themoviedb.org`.
- Preserve video extensions. Keep only tags that the naming reference's whitelist recognizes, in its defined order, and drop the tokens its "Tokens to drop" section lists — embedded-subtitle and language markers such as `中英字幕` or `.chs.eng`, site and channel watermarks, and quality words that duplicate a real tag. "Preserve useful tags" is not "preserve whatever the source wrote".
- Never accept the script's default `new_name` as the target when a TMDB identity has been resolved. The default is derived from the source stem, so it carries the source's casing and its whole tail through unchanged — `rain.dogs.S01E01...` stays lowercase, `1080p中英字幕` stays intact. Build the target from the canonical title and a filtered tail, then pass it to `approve --new-name`. Before approving, check the target against three things the script does not validate: the title segment matches the resolved TMDB title's spelling and capitalization, the filename contains no CJK text, and every tail token is on the whitelist.
- For every TV series whose ID is verified, fetch the `en-US` episode titles for each season in the batch through the fixed contract in [references/tmdb-api.md](references/tmdb-api.md), and put them in the episode filenames. This is required, not opportunistic: a source filename with no episode title still gets the canonical one added, and a source filename with a localized one gets it replaced. Match on `episode_number` only. Show the fetched titles alongside the mappings when the batch goes to the user.
- Put a verified movie TMDB ID in `{tmdb-ID}` immediately after the year. Store a TV series ID and first-air year in the plan and series folder; do not inject either into episode filenames.
- Apply the query-language default only to second-level folder labels. Keep video filenames canonical for stable scraping.
- Accept only exact direct-child mappings in `folder-plan`. `organize-plan` additionally accepts sources and a destination nested under the root, expressed as relative paths whose every segment is validated; it refuses `.`, `..`, absolute values, and anything that resolves outside the root. Both refuse root `/`, more than 20 folders, non-directory sources, duplicate targets, occupied targets, and unsafe cross-platform names. `organize-plan` also refuses two selected sources where one contains the other, because moving the outer one would carry the inner one with it and strand the second move.
- Pair only clearly matching external subtitle files and preserve language suffixes.
- Leave undocumented multi-episode patterns and low-confidence parent-folder inferences in `review`.
- Prefer AList's single-file rename endpoint over batch/regex rename so each mutation is journaled and reversible.
