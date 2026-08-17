# AList Infuse + VidHub Namer

[中文文档](README.zh-CN.md)

> A portable CLI and agent skill for producing reviewable AList media naming and folder-organization plans for Infuse and VidHub. It scans first, changes nothing by default, and applies only explicitly approved, small batches of in-place operations.

## What it does

Use this skill when an AList-mounted media library needs predictable names and layouts that Infuse or VidHub can scrape reliably. It can:

- scan a media path and generate a dry-run JSON and CSV plan;
- parse local filenames or, with the user's own TMDB token, attach read-only TMDB candidates;
- normalize movie, episode, special, and subtitle names;
- create `Movies/` or `TV Shows/` folder layouts through exact, limited folder moves;
- keep a local SQLite ledger of processed paths and rebuild that ledger from journals;
- preview, apply, and roll back approved plans.

The bundled script only calls the AList endpoints needed to list, rename, create a direct-child directory, and move one approved folder at a time. It does not download media, call cloud-storage provider APIs, delete files, upload files, copy files, or perform recursive moves.

## Current status

The repository contains a working implementation and documentation, and the unit tests pass. Treat the mutation workflow as **not release-ready** until you have completed a canary against your own AList instance.

## Before you start

- Use a temporary, least-privilege AList account whose base path is the parent of a narrow test folder such as `/Canary`.
- Use HTTPS when possible. Plain HTTP exposes credentials and tokens on the network.
- Keep tokens, plans, journals, and the local ledger in an ignored `work/` directory. They can contain media paths and operational history.
- Supply your own TMDB Read Access Token only after reviewing TMDB's current terms. The skill never ships or shares a TMDB credential.
- Start with a 1–20 item canary. Inspect results in AList and rescan only the affected source in Infuse or VidHub before expanding.

## Quick start

Clone the repository and run the CLI from a terminal, script, or agent harness. Read [SKILL.md](SKILL.md) when your harness supports skill instructions.

The CLI uses Python's standard library. From the repository root:

```bash
python3 scripts/alist_vidhub_namer.py --help
```

Create a temporary AList token without putting a password in shell history:

```bash
export ALIST_URL='https://alist.example.test'
export ALIST_USERNAME='alist-canary'
python3 scripts/alist_vidhub_namer.py login --token-file work/alist-canary.token
export ALIST_TOKEN_FILE="$PWD/work/alist-canary.token"
```

Check the target, then produce a read-only plan:

```bash
python3 scripts/alist_vidhub_namer.py check --path '/Canary'

python3 scripts/alist_vidhub_namer.py plan \
  --path '/Canary' \
  --kind auto \
  --resolver none \
  --output work/media-plan.json \
  --csv work/media-plan.csv
```

Use `--resolver auto` after configuring a user-owned TMDB token. It falls back to local parsing when no token exists; use `--resolver none` when the plan must make no TMDB request.

## Safe workflow

| Stage | Your action | Remote change? |
| --- | --- | --- |
| 1. Connect | Create a low-privilege account and run `check`. | No |
| 2. Plan | Run `plan`, `pending-report`, `folder-plan`, or `organize-plan`. | No |
| 3. Review | Inspect every mapping and resolve `review` and `conflict` entries. | No |
| 4. Canary | Select 1–20 exact videos, preview `apply`, then explicitly confirm the root and count. | Only after `--execute` |
| 5. Verify | Check AList and rescan the affected source in Infuse or VidHub. | No |
| 6. Recover | Preview `rollback` before explicitly executing it. | Only after `--execute` |

An ordinary request to scan, research, audit, or plan does not authorize a remote rename. The script refuses mutations at `/`, stops on stale paths or target conflicts, and writes journals after every successful mutation.

### Batch auto-execute mode

For repeated work in one personal library, opt in once per session to remove redundant per-item approvals. The skill may then approve and execute **video-name** changes without a separate per-item confirmation, and only when one identity is clear, the plan has no destination conflict, the live layout matches the plan, and confidence meets the plan threshold.

Folder-name renames and directory moves into `Movies/` or `TV Shows/` are never automatic in this mode. A folder rename rewrites every descendant path and invalidates the paths recorded in earlier video journals, so both classes wait for one explicit confirmation covering the whole batch: you review every folder pending a rename or a move, then give a single combined go.

## Naming model

Movies use a stable TMDB ID in the folder and file name after manual verification:

```text
Movies/
  Inception (2010) {tmdb-27205}/
    Inception.2010.{tmdb-27205}.1080p.BluRay.x264.DTS.mkv
```

For predominantly Chinese requests, the media-folder label can use `localized + canonical` form:

```text
Movies/
  盗梦空间 Inception (2010) {tmdb-27205}/
```

TV episode filenames use the series title and episode number. The series TMDB ID and first-air year remain in the series folder and plan rather than every episode filename:

```text
TV Shows/
  The Pitt (2025) {tmdb-12345}/
    Season 01/
      The.Pitt.S01E01.1080p.WEB-DL.mkv
      The.Pitt.S01E01.1080p.WEB-DL.zh-CN.srt
```

## Before and after examples

These examples use filename patterns from a local scan while omitting server and mount details. They illustrate a confirmed plan, not an automatic match: verify the title, year, episode, language, and TMDB ID before approval.

### Movie folder and filename

```text
Before
  [为所应为][1989][英语中字][1080P][780MB]/
    [为所应为].Do.the.Right.Thing.1989.BD.MiniSD-TLF.mkv

After
  Movies/为所应为 Do the Right Thing (1989) {tmdb-925}/
    Do.the.Right.Thing.1989.{tmdb-925}.BD.MiniSD-TLF.mkv
```

The plan removes share-folder noise, preserves useful release tags, and adds the verified movie ID. A paired subtitle would use the complete target video stem followed by its existing language suffix.

### TV episode

```text
Before
  先见之明.S01E01.HD1080P.YYeTs.中英双字.霸王龙压制组T-Rex.mp4

After
  The.OA.S01E01.Homecoming.1080p-YYeTs.mp4
```

The plan resolves the Chinese title, removes subtitle and encoder noise, and keeps the source-evidenced release group. `Homecoming` comes from TMDB's `en-US` episode list: the episode title is a required field, added even when the source filename omits it. The series year and ID belong in the series folder and plan, while the episode file keeps the series title and normalized `SxxEyy` key.

### Folder organization

```text
Before
  the vince staple show/

After
  TV Shows/The Vince Staples Show (2024) {tmdb-243861}/
```

The plan corrects capitalization and adds the verified year and ID. Moving a folder and renaming a video use separate plans and journals. Review both operations before execution, then roll them back in reverse dependency order if needed.

## Common commands

| Command | Purpose |
| --- | --- |
| `check` | Read AList version, storage provider, and write status. |
| `plan` | Recursively generate a dry-run media plan. |
| `pending-report` | Filter out paths already processed under the current rule version. |
| `tmdb-setup` / `tmdb-check` | Store and validate a user-owned TMDB token. |
| `approve` | Add one manually verified mapping to a copy of a plan. |
| `select` | Build a 1–20 video canary from exact paths. |
| `apply` / `rollback` | Preview or execute an approved video or folder-rename plan. |
| `organize-plan` / `organize-apply` / `organize-rollback` | Plan, apply, or reverse exact moves into `Movies/` or `TV Shows/`. |
| `state-init` / `state-status` / `state-rebuild` | Manage the local, version-aware processing ledger. |

Read [SKILL.md](SKILL.md) for the full operating contract. The detailed references cover [AList API safety](references/api-and-safety.md), [naming rules](references/naming.md), [TMDB use](references/tmdb-api.md), [state tracking](references/state-ledger.md), and [Chinese examples](references/usage-zh-CN.md).

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## License

No license file is included yet. Do not assume you may redistribute or reuse the code under an open-source license until the repository owner adds one.
