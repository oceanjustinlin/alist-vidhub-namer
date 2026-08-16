# Infuse + VidHub naming reference

Read this reference when generating or reviewing a rename plan.

## Compatibility policy

- The filename is authoritative. VidHub documents that folder structure does not affect scraping, so every video filename must contain its own identity fields.
- Use the TMDB canonical/original title spelling for identity. Let the player display localized metadata; do not put two translated titles in the same filename unless manual testing proves that library needs it.
- Always include the movie release year. Keep a TV series first-air year in its series folder and local TMDB mapping, but omit it from episode filenames.
- Use dots in filenames and readable spaces in directory names. Infuse treats spaces, dots, underscores, and dashes as equivalent, while this one-style rule keeps the library deterministic.
- Put identity first, then edition/episode title, then technical tags.
- Never invent a TMDB ID. Record only a manually verified ID.

## Second-level folder language

The second-level media folder means the folder directly below `Movies/` or `TV Shows/`.

Available modes:

- `localized + canonical`: `Localized Title Canonical Title (Year) {tmdb-ID}`
- `canonical only`: `Canonical Title (Year) {tmdb-ID}`

Default selection:

- Predominantly Chinese query: `localized + canonical`
- Predominantly English query: `canonical only`
- Explicit user choice: always overrides the default

Examples:

```text
Movies/盗梦空间 Inception (2010) {tmdb-27205}/
TV Shows/绝命毒师 Breaking Bad (2008) {tmdb-1396}/
```

Canonical-only equivalents:

```text
Movies/Inception (2010) {tmdb-27205}/
TV Shows/Breaking Bad (2008) {tmdb-1396}/
```

This is a display and organization preference only. Keep the files inside canonical:

```text
Inception.2010.{tmdb-27205}.1080p.BluRay.x264.DTS.mkv
Breaking.Bad.S01E01.Pilot.1080p.BluRay.x265.DTS.mkv
```

Do not repeat the title when localized and canonical names are identical. Sanitize both names for the filesystem. Never invent a translation; if the localized title has not been verified, use canonical-only and mark the proposed folder label for review.

## Directory layout

```text
Movies/
  [Localized Title ]Movie Title (Year) {tmdb-MOVIE_ID}/
    Movie.Title.Year.{tmdb-MOVIE_ID}.Resolution.Source.VideoCodec.AudioCodec.ext

TV Shows/
  [Localized Title ]Series Title (FirstAirYear) {tmdb-SERIES_ID}/
    Season 00/
    Season 01/
      Series.Title.S01E01.Episode.Title.Resolution.Source.VideoCodec.AudioCodec.ext
```

The current script renames files in place; it does not move files or create this directory tree. Treat directory reorganization as a separate, explicitly approved operation.

## Movies

Canonical folder and filename:

```text
/Movies/盗梦空间 Inception (2010) {tmdb-27205}/
  Inception.2010.{tmdb-27205}.1080p.BluRay.x264.DTS.mkv
  Inception.2010.{tmdb-27205}.1080p.BluRay.x264.DTS.zh-CN.srt
```

Rules:

1. Start with the complete movie title.
2. Always add the release year.
3. Add the verified movie ID as `{tmdb-ID}` immediately after the year. This is Infuse's documented filename syntax; VidHub still sees the title and year at the start of the name.
4. Put a recognized edition after the ID, for example `Final.Cut`, `Directors.Cut`, `Extended`, or `IMAX`. Infuse also supports custom `{edition-...}` tags, but use those only when Infuse-specific edition grouping is required.
5. Put technical tags last.

Movie template:

```text
Movie.Title.Year.{tmdb-ID}[.Edition][.Resolution][.Source][.DynamicRange][.VideoCodec][.AudioCodec][-ReleaseGroup].ext
```

## TV series

Canonical folder and filenames:

```text
/TV Shows/中文剧名 Series Title (2021) {tmdb-SERIES_ID}/
  Season 01/
    Series.Title.S01E01.Episode.Title.2160p.WEB-DL.HDR.x265.DDP5.1.mkv
    Series.Title.S01E01.Episode.Title.2160p.WEB-DL.HDR.x265.DDP5.1.zh-CN.srt
  Season 00/
    Series.Title.S00E01.Special.Title.1080p.WEB-DL.x264.AAC.mkv
```

Rules:

1. Start every episode filename with the complete series title.
2. Add `SxxEyy` with two-digit season and episode numbers. This is the shared high-confidence key for Infuse and VidHub.
3. Do not add the series first-air year to an episode filename. Keep it in the series folder and local TMDB mapping instead.
4. Episode title is optional and comes immediately after `SxxEyy`.
5. Put the verified series-level TMDB ID in the series folder and in the local plan's `tmdb_id` field. Do not inject it into episode filenames by default: Infuse's official ID example is documented for movies, and TV filename-ID behavior has been reported as inconsistent. The episode filename must remain independently matchable by title/`SxxEyy`.
6. Use `Season 00` and `S00Eyy` for specials. Use `Season 01` for miniseries and anime unless the source metadata explicitly defines another season.

TV template:

```text
Series.Title.SxxEyy[.Episode.Title][.Resolution][.Source][.DynamicRange][.VideoCodec][.AudioCodec][-ReleaseGroup].ext
```

VidHub does not document a reliable multi-episode filename form. Leave combined releases such as `S01E01-E02` in `review`; splitting to one file per episode is the safest shared convention.

## Technical tag order

Use this order when tags exist:

```text
Edition -> Resolution -> Source -> DynamicRange -> VideoCodec -> AudioCodec -> ReleaseGroup
```

Examples include `2160p`, `WEB-DL`, `BluRay`, `REMUX`, `HDR10`, `DV`, `x265`, `AV1`, `DDP5.1`, `TrueHD.Atmos`. Technical tags are optional and never replace identity fields.

## External subtitles

Keep each local subtitle in the video's directory. Its filename must equal the complete video stem plus an optional language suffix. The planner pairs `.srt`, `.ass`, `.ssa`, `.sub`, `.vtt`, `.smi`, and `.idx` files whose stems equal or extend a video stem.

```text
Movie.Title.2024.{tmdb-12345}.1080p.mkv
Movie.Title.2024.{tmdb-12345}.1080p.zh-CN.srt
```

Do not rename unrelated sidecars automatically.

## Filesystem safety

- Replace `"`, `\`, `/`, `:`, `|`, `<`, `>`, `*`, and `?` in titles before creating a cross-platform filename.
- Preserve the original media extension.
- Keep one media item per identity. Do not place several unrelated cuts or episodes behind an ambiguous common stem.

## Sources

- Infuse Metadata 101: https://support.firecore.com/hc/zh-tw/articles/215090947-%E5%85%83%E6%95%B8%E6%93%9A-101
- Infuse local metadata overrides: https://support.firecore.com/hc/en-us/articles/4405042929559-Overriding-Artwork-and-Metadata
- VidHub Chinese naming convention: https://zh.vidhub.okaapps.com/vidhub-file-naming-convention/
- VidHub file-source behavior: https://zh.vidhub.okaapps.com/use-file-source/
- VidHub playback/subtitle behavior: https://zh.vidhub.okaapps.com/video-playback/
- Firecore community report on TV filename IDs: https://community.firecore.com/t/metadata-inconsistencies-and-ignored-tmdb-id/59080
