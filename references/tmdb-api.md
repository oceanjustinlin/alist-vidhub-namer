# TMDB BYOK API contract

Read this reference before enabling TMDB lookup. The bundled script is the only component that may construct TMDB requests; do not improvise API calls in the agent workflow.

## User-owned credential

Require each user to register their own TMDB application and review the current API terms:

- Registration: https://www.themoviedb.org/settings/api
- Terms: https://www.themoviedb.org/api-terms-of-use

Accept only an API Read Access Token through `TMDB_READ_TOKEN` or a mode-0600 `TMDB_TOKEN_FILE`. Prefer the file. Never put the token in arguments, plans, journals, CSV files, logs, Git, screenshots, or shared archives.

TMDB currently restricts use of its API or content in connection with AI/LLM applications. Treat BYOK as an explicit opt-in: show the terms, require the user to accept them, and do not present this Skill as granting permission. Commercial use requires a separate agreement with TMDB.

## Fixed endpoints

Base URL: `https://api.themoviedb.org`

The local script uses only these read-only requests:

```text
GET /3/authentication
GET /3/search/movie
GET /3/search/tv
GET /3/tv/{series_id}/season/{season_number}
```

Authenticate every request with:

```text
Authorization: Bearer USER_API_READ_ACCESS_TOKEN
Accept: application/json
```

Movie search parameters:

```text
query              required string
year               optional release year
language           default en-US
include_adult      false
page               1
```

Consume only `results[].id`, `title`, `original_title`, and `release_date`.

When the extracted query contains CJK characters and the requested output language is not `zh-CN`, repeat the same search with `language=zh-CN`, merge results by TMDB ID, keep the canonical title from the requested output language, and use the localized response only as additional matching evidence.

TV search parameters:

```text
query                  required string
first_air_date_year    optional first-air year
language               default en-US
include_adult          false
page                   1
```

Consume only `results[].id`, `name`, `original_name`, and `first_air_date`.

Season parameters:

```text
language           default en-US
```

Consume only `episodes[].episode_number` and `episodes[].name`. Call this once per series and season, after the series ID is verified, to get the canonical episode titles required by [naming.md](naming.md). Reach it through the bundled `TMDBClient.request` method; no CLI subcommand wraps it, and it is still the fixed contract, so never hand-build the request or add parameters. Match strictly on `episode_number`; if a number is missing from the response, drop that episode's title rather than shifting the list.

Do not request images, credits, overviews, recommendations, watch providers, account data, or write endpoints.

Official contracts:

- https://developer.themoviedb.org/reference/authentication-validate-key
- https://developer.themoviedb.org/reference/search-movie
- https://developer.themoviedb.org/reference/search-tv
- https://developer.themoviedb.org/reference/tv-season-details

## Retry and rate policy

- Default to 5 requests per second and refuse values above 20.
- Retry only `429`, `500`, `502`, `503`, and `504`, at most five attempts.
- Honor `Retry-After` when present; otherwise use bounded exponential backoff.
- Never retry `401` or `403`; ask the user to replace or review the credential.
- Use a finite request timeout.

TMDB documents a changing upper limit around 40 requests per second. Do not target that ceiling.

## Resolution boundary

The resolver adds at most three minimal candidates to the local plan. It scores translated/original title similarity, exact year, and result rank. Even an exact candidate remains `review` until the user confirms the displayed old path, suggested filename, TMDB ID, and TMDB URL.

Preserve an explicit year already present in the source filename when generating the suggestion. Treat a one-year TMDB date difference as review evidence rather than silently replacing a festival-premiere year with a later wide-release year.

The candidate cache contains no token and no synopsis or image data. Do not retain API-derived candidates longer than six months.
