# AList Infuse + VidHub Namer

[中文文档](README.zh-CN.md)

> A Codex skill for producing reviewable AList media naming and folder-organization plans for Infuse and VidHub. It scans first, changes nothing by default, and applies only explicitly approved, small batches of in-place operations.

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

The repository contains an initial working implementation and documentation. At the current commit, two filename-parsing unit tests fail around stripping Chinese subtitle/release notes. Treat the mutation workflow as **not release-ready** until those tests pass and you have completed a canary against your own AList instance.

## Before you start

- Use a temporary, least-privilege AList account whose base path is the parent of a narrow test folder such as `/Canary`.
- Use HTTPS when possible. Plain HTTP exposes credentials and tokens on the network.
- Keep tokens, plans, journals, and the local ledger in an ignored `work/` directory. They can contain media paths and operational history.
- Supply your own TMDB Read Access Token only after reviewing TMDB's current terms. The skill never ships or shares a TMDB credential.
- Start with a 1–20 item canary. Inspect results in AList and rescan only the affected source in Infuse or VidHub before expanding.

## Quick start

Clone the repository and make the directory available to Codex as the `alist-vidhub-namer` skill. In Codex, invoke it as `$alist-vidhub-namer`.

The CLI uses Python's standard library. From the repository root:

```bash
python3 scripts/alist_vidhub_namer.py --help
```

Create a temporary AList token without putting a password in shell history:

```bash
export ALIST_URL='https://alist.example.test'
export ALIST_USERNAME='codex-canary'
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
