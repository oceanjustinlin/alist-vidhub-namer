# Processing state ledger

Use the local SQLite ledger to skip media already processed under the current naming rules. The ledger never resides in an AList mount and never stores credentials.

## Version model

Track three independent version classes:

- `state_schema_version`: database structure and migrations;
- component rule versions: movie file, TV episode, subtitle, media folder, and library layout;
- `skill_version`: release provenance only.

Do not invalidate processed files merely because the Skill release changes. Return `needs_recheck` only when the relevant component rule version changes.

## Identity and classifications

Use AList instance fingerprint plus current full path as the primary lookup. Store size and modified time when available. A unique size/modified match at another path is only `moved_externally`, never an automatic identity update. TMDB ID identifies a work, not a particular encode, so never use it as the file key.

`pending-report` classifies scanned media as:

- `processed_current`: recorded metadata and relevant rule version still match;
- `needs_recheck`: the applicable naming rule version changed;
- `changed_since_processed`: recorded size or modified time changed;
- `moved_externally`: one probable prior record exists at another path;
- `rolled_back`: a recorded rename was reversed;
- `compliant_untracked`: currently compliant but not created by a recorded run;
- `ready`, `review`, or `conflict`: unprocessed plan status.

The default report contains only actionable states. Add `--include-processed` for a complete inventory.

## Commands

Initialize or inspect the default database:

```bash
python3 scripts/alist_vidhub_namer.py state-init
python3 scripts/alist_vidhub_namer.py state-status
```

Fast local-rule scan with no TMDB calls:

```bash
python3 scripts/alist_vidhub_namer.py pending-report \
  --path '/MediaLibrary/Movies' \
  --resolver none \
  --output work/pending.json \
  --csv work/pending.csv
```

`apply`, `rollback`, `organize-apply`, and `organize-rollback` use `work/alist-vidhub-state.sqlite` by default. Override it consistently with `--state-db`. A ledger update failure never hides a successful remote mutation: preserve the journal, report the warning, then rebuild into a new database.

Rebuild by passing exact journals from oldest to newest. The output database must not exist:

```bash
python3 scripts/alist_vidhub_namer.py state-rebuild \
  --journal work/video-journal.json \
  --journal work/folder-journal.json \
  --journal work/organize-journal.json \
  --output-db work/rebuilt-state.sqlite
```

Journals remain the immutable recovery/audit source. The SQLite database is a derived acceleration index. Do not include a user's database or journals in a shared Skill archive; they reveal media paths and processing history.
