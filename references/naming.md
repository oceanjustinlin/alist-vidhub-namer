# Infuse + VidHub naming reference

Read this reference when generating or reviewing a rename plan.

## Compatibility policy

- The filename is authoritative. VidHub documents that folder structure does not affect scraping, so every video filename must contain its own identity fields.
- Use the TMDB canonical/original title spelling for identity, including its capitalization. A source file named `rain.dogs.S01E01...` becomes `Rain.Dogs.S01E01...`; never carry the source's casing into the target just because the target is otherwise correct. Let the player display localized metadata; do not put two translated titles in the same filename unless manual testing proves that library needs it.
- A video filename is canonical-only. No localized title, no localized episode title, no CJK text of any kind belongs in it, even when the folder label is `localized + canonical`. `黑镜.S06E01.琼糟透了.mp4` is wrong; `Black.Mirror.S06E01.Joan.Is.Awful.mp4` is right.
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

Every `Season NN/` subfolder is mandatory for a show with genuine season metadata, including its first season — do not leave episodes loose directly in the series folder just because only one season has been shared so far. Check TMDB's `type` and `number_of_seasons` on the series: `Scripted`/`Documentary`/etc. with more than one season, or any `status` of `Returning Series`, gets the `Season NN` wrapper even when only one season's files currently exist locally, since more will land later. The one exception is a true `type: "Miniseries"` with `number_of_seasons: 1` and `status: "Ended"` — TMDB itself does not expect another season, so its episodes sit directly in the series folder with no `Season 01` wrapper. When adding a later season to a show whose earlier season was left flat by an earlier mistake, wrap the earlier season into its own `Season NN` folder in the same batch rather than leaving a mixed flat/nested structure — see the `season-wrap-plan`/`season-wrap-apply` commands in [api-and-safety.md](api-and-safety.md), built for exactly this retrofit.

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
4. Episode title comes immediately after `SxxEyy` and must be the TMDB `en-US` episode name for that exact season and episode number. Fetch the season's episode list once the series ID is verified and fill the title in — it is a field to populate, not one to leave out because the source filename lacked it. A localized episode title is replaced with the verified `en-US` name; never transliterate or translate one by hand. Drop the title when TMDB has no `en-US` name for that episode number, or when TMDB's name is a generic `Episode 1`/`Episode 2` placeholder that only restates the `SxxEyy` key already in the filename — some limited series were never given individual episode titles in TMDB's own database. Say so in the plan summary rather than guessing a replacement.
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

Write each tag in its conventional spelling regardless of how the source wrote it: `web` becomes `WEB`, `bd` becomes `BluRay`, `remux` becomes `REMUX`, `aac` becomes `AAC`. Leave a release-group token's own capitalization alone (`h264-cakes`, `x264-NTb`).

## Tokens to drop

The tag order above is a whitelist, not a suggestion. A token that is neither an identity field nor a recognized technical tag does not belong in the filename. Drop these when normalizing:

- **Embedded-subtitle and language markers.** `中英字幕`, `中英双字`, `简繁英字幕`, `中字`, `双语`, `国语`, and their Latin equivalents `.chs`, `.cht`, `.chs.eng`, `.CHS`, `.zh`, `.cn`. These describe subtitle tracks inside the container, which the player reads from the file itself; they are not release metadata and they sit outside the tag order. Note the contrast with external subtitle sidecars below, where a trailing language suffix is required, not forbidden.
- **Site, channel, and forum watermarks.** `[EZTVx.to]`, `@TheTaoSong`, `SW-115`, `亿万同人字幕组`, `守望电影`. A real scene release group stays as the `-ReleaseGroup` suffix; a distribution watermark does not become one.
- **Vague quality words that duplicate a real tag.** `HD` next to `1080p`.

Do not drop a token merely because it is unfamiliar. If a token might be a legitimate release group or edition, leave the entry in `review` and ask.

## Worked examples

Source names taken from a real library, paired with the canonical target each one
must reach. Every pair shows a failure mode the planner's default target does not
fix on its own, because that default is derived from the source stem.

Note what every TV target below has in common: an `en-US` episode title sits
immediately after `SxxEyy`, whether or not the source filename had one. Only the
Barry source already carried a usable title; every other title here came from the
season endpoint, fetched once the series ID was verified.

```text
# Source casing is not canonical casing, and the source carried no episode
# title. Fix the case, fetch the title, drop the language markers.
rain.dogs.S01E01.1080p.web.h264-cakes.chs.eng.mp4
Rain.Dogs.S01E01.It's.Hard.to.Be.a.Saint.in.the.City.1080p.WEB.h264-cakes.mp4

# A language marker fused to a real tag: keep the tag, drop the marker.
# TMDB's title is "7:00 A.M."; colons are sanitized to dots.
The.Pitt.S01E01.1080p中英字幕.mp4
The.Pitt.S01E01.7.00.A.M.1080p.mp4

# Same marker in Latin script, after the release group. Here the source's
# episode title already matched TMDB ("yikes"), so it stays as-is.
Barry.S04E01.yikes.1080p.HMAX.WEB-DL.DDP5.1.x264-NTb.chs.eng.mp4
Barry.S04E01.yikes.1080p.HMAX.WEB-DL.DDP5.1.x264-NTb.mp4

# Localized series title and localized episode title: both replaced from TMDB.
黑镜.S06E01.琼糟透了.mp4
Black.Mirror.S06E01.Joan.Is.Awful.mp4

# Localized title, no tail at all. The episode title is still fetched and
# added — a bare SxxEyy target is not finished. TMDB's title is "1:23:45".
切尔诺贝利.S01E01.mp4
Chernobyl.S01E01.1.23.45.mp4

# Channel watermark and a quality word that duplicates the resolution.
黑帮领地.MobLand.S01E01.中英字幕.1080p.HD.@TheTaoSong.mp4
MobLand.S01E01.Stick.or.Twist.1080p.mp4

# Site tag in brackets attached to a real group: drop the bracket, keep ETHEL.
# A year inside an episode title is fine; the banned year is one before SxxEyy.
Feud.S02E03.1080p.WEB.h264-ETHEL[EZTVx.to].chs.eng.mp4
Feud.S02E03.Masquerade.1966.1080p.WEB.h264-ETHEL.mp4

# Movie: fansub credit is not a release group; the verified ID stays. Movies
# have no episode title — the year and {tmdb-ID} carry the identity instead.
Triangle.of.Sadness.2022.{tmdb-497828}.1080p.中英字幕.亿万同人字幕组.mp4
Triangle.of.Sadness.2022.{tmdb-497828}.1080p.mp4
```

Counter-examples — do not "normalize" these:

```text
# A subtitle sidecar's trailing language suffix is required, not noise.
Nightcrawler.2014.{tmdb-242582}.1080p.REMUX.chs.ass    -> unchanged

# An unfamiliar token that may be a real group or edition stays in `review`.
Some.Show.S01E01.1080p.WEB.x264-QWERTY.mp4             -> ask, do not strip

# A source that already matches the standard is `skip`, not a rewrite.
Inside.No.9.S09E01.Boo.to.a.Goose.1080p.iP.WEB-DL.AAC2.0.H.264-playWEB.mp4

# TMDB has no en-US name for this episode number: drop the title and say so
# in the plan summary. Never invent or translate one.
Some.Show.S01E09.1080p.WEB.x264-NTb.mp4                -> title omitted, noted
```

## External subtitles

Keep each local subtitle in the video's directory. Its filename must equal the complete video stem plus an optional language suffix. The planner pairs `.srt`, `.ass`, `.ssa`, `.sub`, `.vtt`, `.smi`, and `.idx` files whose stems equal or extend a video stem.

```text
Movie.Title.2024.{tmdb-12345}.1080p.mkv
Movie.Title.2024.{tmdb-12345}.1080p.zh-CN.srt
```

Do not rename unrelated sidecars automatically.

## Filesystem safety

- Replace `"`, `\`, `/`, `:`, `|`, `<`, `>`, `*`, and `?` in titles before creating a cross-platform filename. Replace each with the field separator `.`, then collapse any run of dots and trim a trailing one: the episode title `1:23:45` becomes `1.23.45`, and `7:00 A.M.` becomes `7.00.A.M`.
- Normalize typographic quotes to their ASCII form before anything else: TMDB is inconsistent about straight vs. curly punctuation, sometimes within one show's own episode list, so leaving it as-fetched mixes styles across the library. `Mac's` stays `Mac's` however TMDB spelled it; a curly double quote is stripped the same way a straight one is.
- Preserve the original media extension.
- Keep one media item per identity. Do not place several unrelated cuts or episodes behind an ambiguous common stem.

## Sources

- Infuse Metadata 101: https://support.firecore.com/hc/zh-tw/articles/215090947-%E5%85%83%E6%95%B8%E6%93%9A-101
- Infuse local metadata overrides: https://support.firecore.com/hc/en-us/articles/4405042929559-Overriding-Artwork-and-Metadata
- VidHub Chinese naming convention: https://zh.vidhub.okaapps.com/vidhub-file-naming-convention/
- VidHub file-source behavior: https://zh.vidhub.okaapps.com/use-file-source/
- VidHub playback/subtitle behavior: https://zh.vidhub.okaapps.com/video-playback/
- Firecore community report on TV filename IDs: https://community.firecore.com/t/metadata-inconsistencies-and-ignored-tmdb-id/59080
