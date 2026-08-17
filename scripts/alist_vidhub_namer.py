#!/usr/bin/env python3
"""Plan, apply, and roll back Infuse/VidHub-friendly AList media renames.

Uses only the Python standard library. Credentials are read from environment
variables and are never written to plan or journal files.
"""

import argparse
import csv
import getpass
import hashlib
import itertools
import json
import os
import posixpath
import re
import sqlite3
import stat
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 1
SKILL_RELEASE_VERSION = "11.0.0"
MOVIE_FILE_RULE_VERSION = "movie-file-v2"
TV_FILE_RULE_VERSION = "tv-episode-v3"
SUBTITLE_RULE_VERSION = "subtitle-v1"
FOLDER_RULE_VERSION = "media-folder-v1"
ORGANIZATION_RULE_VERSION = "library-layout-v1"
DEFAULT_STATE_DB = "work/alist-vidhub-state.sqlite"
TMDB_API_BASE_URL = "https://api.themoviedb.org"
VIDEO_EXTENSIONS = {
    ".3gp", ".avi", ".flv", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4",
    ".mpeg", ".mpg", ".mts", ".rm", ".rmvb", ".ts", ".webm", ".wmv",
}
SUBTITLE_EXTENSIONS = {".ass", ".idx", ".smi", ".srt", ".ssa", ".sub", ".vtt"}
EPISODE_PATTERNS = [
    re.compile(r"(?i)(?<![A-Za-z0-9])S(?P<season>\d{1,2})[ ._-]*E(?P<episode>\d{1,3})(?!\d)"),
    re.compile(r"(?i)(?<!\d)(?P<season>\d{1,2})x(?P<episode>\d{1,3})(?!\d)"),
    re.compile(r"第\s*(?P<season>\d{1,2})\s*季\s*第\s*(?P<episode>\d{1,3})\s*[集话話]"),
]
MULTI_EPISODE_TAIL_RE = re.compile(
    r"(?i)^[ ._]*(?:E|[-+&][ ._-]*E?)\d{1,3}(?!\d)"
)
YEAR_RE = re.compile(r"(?<!\d)(?P<year>19\d{2}|20\d{2})(?!\d)")
TMDB_TAG_RE = re.compile(r"(?i)\{tmdb-(?P<id>\d+)\}")
TECH_RE = re.compile(
    r"(?ix)(?<![A-Za-z0-9])(?:"
    r"4320p|2160p|1080p|1080i|720p|576p|480p|4k|8k|"
    r"uhd|bluray|blu[ ._-]?ray|bdrip|brrip|web[ ._-]?dl|webrip|web|hdtv|dvdrip|"
    r"remux|proper|repack|extended|uncut|imax|hdr10\+?|hdr|dolby[ ._-]?vision|dv|"
    r"x26[45]|h[ ._-]?26[45]|hevc|av1|10bit|aac|ac3|eac3|ddp?\+?|dts(?:[ ._-]?hd)?|"
    r"truehd|atmos|flac|multi|dual[ ._-]?audio"
    r")(?![A-Za-z0-9])"
)
GENERIC_EPISODE_TITLE_RE = re.compile(r"(?i)^episode\s*\d+$")
CJK_RE = re.compile(
    r"[　-〿㐀-䶿一-鿿豈-﫿＀-￯]"
)
# Subtitle/language markers describe container tracks, not the release.
LANGUAGE_TAG_RE = re.compile(
    r"(?i)^(?:chs|cht|chi|chn|eng|zh|zh[ ._-]?cn|zh[ ._-]?hans|zh[ ._-]?hant|cn|gb|big5|han)"
    r"(?:-(?:chs|cht|chi|chn|eng|zh|cn|gb|big5|han))*$"
)
# Conventional spelling for whitelisted technical tags, keyed by casefold.
TECH_TAG_SPELLING = {
    "web": "WEB", "web-dl": "WEB-DL", "webdl": "WEB-DL", "webrip": "WEBRip",
    "bluray": "BluRay", "blu-ray": "BluRay", "bd": "BluRay",
    "bdrip": "BDRip", "brrip": "BRRip",
    "remux": "REMUX", "hdtv": "HDTV", "dvdrip": "DVDRip", "uhd": "UHD",
    "hdr": "HDR", "hdr10": "HDR10", "hdr10+": "HDR10+", "dv": "DV",
    "imax": "IMAX", "proper": "PROPER", "repack": "REPACK",
    "aac": "AAC", "ac3": "AC3", "eac3": "EAC3", "flac": "FLAC",
    "dts": "DTS", "dts-hd": "DTS-HD", "truehd": "TrueHD", "atmos": "Atmos",
    "hevc": "HEVC", "av1": "AV1",
}
# Distribution watermarks: a channel handle, a share-site id, a bracketed site
# tag. A real scene group stays as the "-ReleaseGroup" half of its own token.
BRACKET_NOISE_RE = re.compile(r"[\[【(（][^\]】)）]*[\]】)）]")
WATERMARK_RE = re.compile(r"(?i)^(?:@\S+|sw-\d+|[a-z]{2,}-\d{3,})$")
# A channel handle can also ride along inside another token ("CHS-HAN@CHAOSPACE").
HANDLE_SUFFIX_RE = re.compile(r"@\S+$")
RESOLUTION_RE = re.compile(
    r"(?i)^(?:4320p|2160p|1080[pi]|720p|576p|480p|4k|8k|\d{3,4}[x×]\d{3,4})$"
)
VAGUE_QUALITY_RE = re.compile(r"(?i)^(?:hd|sd|hq|高清|超清)$")
# Tokens the naming reference recognizes without an explicit spelling entry:
# episode-title words, numeric fragments, and codec/group compounds.
RECOGNIZED_TAG_RE = re.compile(
    r"(?i)^(?:"
    r"\{tmdb-\d+\}|\d+|v\d{1,2}|"
    r"(?:4320p|2160p|1080[pi]|720p|576p|480p|4k|8k|\d{3,4}[x×]\d{3,4})(?:-[\w.+]+)?|"
    r"(?:x26[45]|h[ ._-]?26[45]|hevc|avc|av1|vp9|vc-?1|xvid|divx|10bit|8bit)(?:-[\w.+]+)?|"
    r"(?:aac\d?|ac3|eac3|ddp?[\d+]*|dts(?:-hd)?|ma|truehd|atmos|flac|opus)(?:-[\w.+]+)?|"
    r"(?:web|web-?dl|webrip|bluray|bdrip|brrip|remux|hdtv|hdtvrip|dvdrip|uhd)(?:-[\w.+]+)?|"
    # Streaming platforms and studio sources evidenced by the source name.
    r"(?:ip|hmax|amzn|nf|dsnp|disney\+?|max|hulu|atvp|pcok|stan|itunes|crav)(?:-[\w.+]+)?|"
    r"(?:hdr10\+?|hdr|dovi|dv|sdr|imax|proper|repack|extended|unrated|uncut|final|"
    r"directors|cut|remastered|criterion|cc|hfr|multi)"
    r")$"
)
INVALID_COMPONENT_RE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")
SEPARATOR_RE = re.compile(r"[\s._]+")
BRACKET_EDGE_RE = re.compile(r"^[\[【(（{]+|[\]】)）}]+$")


class ToolError(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def eprint(*args):
    print(*args, file=sys.stderr)


def normalize_base_url(value):
    value = value.strip().rstrip("/")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("ALIST_URL must be an absolute http:// or https:// URL")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ToolError("ALIST_URL must not include a path, query, or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        eprint("WARNING: AList credentials/token will travel over unencrypted HTTP.")
    return value


def join_path(directory, name):
    if directory == "/":
        return "/" + name
    return directory.rstrip("/") + "/" + name


def parent_path(path):
    result = posixpath.dirname(path.rstrip("/"))
    return result or "/"


def atomic_json_write(path, payload):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp-" + uuid.uuid4().hex)
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(temporary), str(destination))


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def alist_instance_id(base_url):
    normalized = str(base_url).strip().rstrip("/")
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("Journal/state AList URL is invalid")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def file_rule_version(media_type):
    return {
        "movie": MOVIE_FILE_RULE_VERSION,
        "tv": TV_FILE_RULE_VERSION,
        "subtitle": SUBTITLE_RULE_VERSION,
    }.get(media_type)


def state_db_from_args(args):
    value = getattr(args, "state_db", None)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


class StateLedger:
    """Local, version-aware index of processed paths. Never stores credentials."""

    def __init__(self, path, create=True, require_new=False):
        self.path = Path(path)
        if require_new and self.path.exists():
            raise ToolError("State database already exists; choose a new --output-db")
        if not create and not self.path.is_file():
            raise ToolError("State database does not exist: {}".format(self.path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        try:
            self.connection = sqlite3.connect(str(self.path))
            self.connection.row_factory = sqlite3.Row
            self._initialize()
        except sqlite3.Error as exc:
            raise ToolError("Could not open state database: {}".format(exc))
        if not existed:
            try:
                os.chmod(str(self.path), 0o600)
            except OSError as exc:
                self.connection.close()
                raise ToolError("Could not protect state database with mode 0600: {}".format(exc))

    def _initialize(self):
        version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if version not in {0, STATE_SCHEMA_VERSION}:
            raise ToolError(
                "Unsupported state schema version {}; expected {}".format(
                    version, STATE_SCHEMA_VERSION
                )
            )
        if version == 0:
            self.connection.executescript("""
                CREATE TABLE state_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id TEXT NOT NULL,
                    current_path TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size INTEGER,
                    modified TEXT,
                    tmdb_id INTEGER,
                    journal_run_id TEXT,
                    file_rule_version TEXT,
                    folder_rule_version TEXT,
                    organization_rule_version TEXT,
                    processed_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    UNIQUE(instance_id, current_path)
                );
                CREATE INDEX assets_fingerprint_idx
                    ON assets(instance_id, size, modified);
                CREATE TABLE state_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    path_before TEXT,
                    path_after TEXT,
                    journal_run_id TEXT,
                    occurred_at TEXT NOT NULL
                );
            """)
            self.connection.execute(
                "INSERT INTO state_meta(key, value) VALUES (?, ?)",
                ("created_by_skill_version", SKILL_RELEASE_VERSION),
            )
            self.connection.execute(
                "INSERT INTO state_meta(key, value) VALUES (?, ?)",
                ("state_schema_version", str(STATE_SCHEMA_VERSION)),
            )
            self.connection.execute("PRAGMA user_version={}".format(STATE_SCHEMA_VERSION))
            self.connection.commit()

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.close()

    def _event(self, instance_id, event_type, before, after, run_id):
        self.connection.execute(
            """INSERT INTO state_events(
                   instance_id, event_type, path_before, path_after,
                   journal_run_id, occurred_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (instance_id, event_type, before, after, run_id, utc_now()),
        )

    def record_processed(self, base_url, entry, current_path, run_id,
                         size=None, modified=None, status="processed"):
        media_type = entry.get("media_type")
        rule = file_rule_version(media_type)
        if rule is None:
            return
        instance_id = alist_instance_id(base_url)
        old_path = entry.get("old_path") or current_path
        target_row = self.connection.execute(
            "SELECT id FROM assets WHERE instance_id=? AND current_path=?",
            (instance_id, current_path),
        ).fetchone()
        source_row = self.connection.execute(
            "SELECT id FROM assets WHERE instance_id=? AND current_path=?",
            (instance_id, old_path),
        ).fetchone()
        if target_row is not None and source_row is not None \
                and target_row["id"] != source_row["id"]:
            raise ToolError("State target is already owned by another asset: {}".format(current_path))
        tmdb_id = entry.get("tmdb_id")
        values = (
            current_path, entry.get("original_path") or old_path, media_type,
            size, modified, tmdb_id, run_id, rule,
            entry.get("folder_rule_version"), entry.get("organization_rule_version"),
            utc_now(), status,
        )
        if source_row is not None:
            self.connection.execute(
                """UPDATE assets SET
                       current_path=?, original_path=?, media_type=?, size=?, modified=?,
                       tmdb_id=?, journal_run_id=?, file_rule_version=?,
                       folder_rule_version=COALESCE(?, folder_rule_version),
                       organization_rule_version=COALESCE(?, organization_rule_version),
                       processed_at=?, status=?
                   WHERE id=?""",
                values + (source_row["id"],),
            )
        else:
            self.connection.execute(
                """INSERT INTO assets(
                       instance_id, current_path, original_path, media_type, size, modified,
                       tmdb_id, journal_run_id, file_rule_version, folder_rule_version,
                       organization_rule_version, processed_at, status
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(instance_id, current_path) DO UPDATE SET
                       original_path=excluded.original_path,
                       media_type=excluded.media_type,
                       size=excluded.size,
                       modified=excluded.modified,
                       tmdb_id=excluded.tmdb_id,
                       journal_run_id=excluded.journal_run_id,
                       file_rule_version=excluded.file_rule_version,
                       folder_rule_version=COALESCE(excluded.folder_rule_version, folder_rule_version),
                       organization_rule_version=COALESCE(
                           excluded.organization_rule_version, organization_rule_version
                       ),
                       processed_at=excluded.processed_at,
                       status=excluded.status""",
                (instance_id,) + values,
            )
        self._event(instance_id, status, old_path, current_path, run_id)
        self.connection.commit()

    def rewrite_prefix(self, base_url, old_prefix, new_prefix, run_id,
                       folder_version=None, organization_version=None):
        instance_id = alist_instance_id(base_url)
        rows = self.connection.execute(
            "SELECT * FROM assets WHERE instance_id=?", (instance_id,)
        ).fetchall()
        changed = 0
        for row in rows:
            current = row["current_path"]
            if not path_is_within(old_prefix, current):
                continue
            suffix = current[len(old_prefix):]
            target = new_prefix + suffix
            occupied = self.connection.execute(
                "SELECT id FROM assets WHERE instance_id=? AND current_path=? AND id<>?",
                (instance_id, target, row["id"]),
            ).fetchone()
            if occupied is not None:
                raise ToolError("State prefix rewrite target is occupied: {}".format(target))
            self.connection.execute(
                """UPDATE assets SET current_path=?,
                       folder_rule_version=COALESCE(?, folder_rule_version),
                       organization_rule_version=COALESCE(?, organization_rule_version),
                       journal_run_id=?, processed_at=? WHERE id=?""",
                (target, folder_version, organization_version, run_id, utc_now(), row["id"]),
            )
            self._event(instance_id, "path_rewrite", current, target, run_id)
            changed += 1
        self.connection.commit()
        return changed

    def mark_rolled_back(self, base_url, current_path, original_path, media_type, run_id):
        instance_id = alist_instance_id(base_url)
        row = self.connection.execute(
            "SELECT id FROM assets WHERE instance_id=? AND current_path=?",
            (instance_id, current_path),
        ).fetchone()
        if row is None:
            entry = {"old_path": original_path, "media_type": media_type}
            self.record_processed(
                base_url, entry, original_path, run_id, status="rolled_back"
            )
            return
        occupied = self.connection.execute(
            "SELECT id FROM assets WHERE instance_id=? AND current_path=? AND id<>?",
            (instance_id, original_path, row["id"]),
        ).fetchone()
        if occupied is not None:
            raise ToolError("State rollback target is occupied: {}".format(original_path))
        self.connection.execute(
            """UPDATE assets SET current_path=?, status='rolled_back',
                   journal_run_id=?, processed_at=? WHERE id=?""",
            (original_path, run_id, utc_now(), row["id"]),
        )
        self._event(instance_id, "rolled_back", current_path, original_path, run_id)
        self.connection.commit()

    def classify(self, base_url, entry):
        instance_id = alist_instance_id(base_url)
        path = entry["old_path"]
        row = self.connection.execute(
            "SELECT * FROM assets WHERE instance_id=? AND current_path=?",
            (instance_id, path),
        ).fetchone()
        if row is not None:
            if row["status"] == "rolled_back":
                return "rolled_back", row
            expected_rule = file_rule_version(entry.get("media_type"))
            if expected_rule and row["file_rule_version"] != expected_rule:
                return "needs_recheck", row
            if row["size"] is not None and entry.get("size") is not None \
                    and int(row["size"]) != int(entry["size"]):
                return "changed_since_processed", row
            if row["modified"] and entry.get("modified") \
                    and str(row["modified"]) != str(entry["modified"]):
                return "changed_since_processed", row
            return "processed_current", row
        size = entry.get("size")
        modified = entry.get("modified")
        if size is not None and modified:
            candidates = self.connection.execute(
                """SELECT * FROM assets WHERE instance_id=? AND size=? AND modified=?
                   AND status<>'rolled_back'""",
                (instance_id, int(size), str(modified)),
            ).fetchall()
            if len(candidates) == 1:
                return "moved_externally", candidates[0]
        reasons = set(entry.get("reason") or [])
        benign = {"already_compliant", "already_normalized_but_requires_review", "paired_subtitle"}
        if entry.get("new_name") == entry.get("old_name") and reasons.issubset(benign):
            return "compliant_untracked", None
        return entry.get("status") or "review", None

    def summary(self):
        counts = self.connection.execute(
            "SELECT status, COUNT(*) AS count FROM assets GROUP BY status ORDER BY status"
        ).fetchall()
        events = self.connection.execute("SELECT COUNT(*) FROM state_events").fetchone()[0]
        return {
            "state_schema_version": STATE_SCHEMA_VERSION,
            "skill_version": SKILL_RELEASE_VERSION,
            "rules": {
                "movie_file": MOVIE_FILE_RULE_VERSION,
                "tv_episode": TV_FILE_RULE_VERSION,
                "subtitle": SUBTITLE_RULE_VERSION,
                "folder": FOLDER_RULE_VERSION,
                "organization": ORGANIZATION_RULE_VERSION,
            },
            "assets_by_status": {row["status"]: row["count"] for row in counts},
            "event_count": events,
        }


class AListClient:
    def __init__(self, base_url, token=None, username=None, password=None, timeout=30):
        self.base_url = normalize_base_url(base_url)
        self.token = token or ""
        self.username = username or ""
        self.password = password
        self.timeout = timeout

    @classmethod
    def from_environment(cls, timeout=30, interactive=False):
        base_url = os.environ.get("ALIST_URL", "")
        if not base_url:
            raise ToolError("Set ALIST_URL before connecting to AList")
        token = os.environ.get("ALIST_TOKEN", "")
        token_file = os.environ.get("ALIST_TOKEN_FILE", "")
        if token and token_file:
            raise ToolError("Set only one of ALIST_TOKEN or ALIST_TOKEN_FILE")
        if token_file:
            source = Path(token_file)
            try:
                mode = stat.S_IMODE(source.stat().st_mode)
            except OSError as exc:
                raise ToolError("Could not read ALIST_TOKEN_FILE metadata: {}".format(exc))
            if not source.is_file():
                raise ToolError("ALIST_TOKEN_FILE must be a regular file")
            if mode & 0o077:
                raise ToolError("ALIST_TOKEN_FILE must not be accessible by group or other users")
            if source.stat().st_size > 16384:
                raise ToolError("ALIST_TOKEN_FILE is unexpectedly large")
            try:
                token = source.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ToolError("Could not read ALIST_TOKEN_FILE: {}".format(exc))
            if not token:
                raise ToolError("ALIST_TOKEN_FILE is empty")
        username = os.environ.get("ALIST_USERNAME", "")
        password = os.environ.get("ALIST_PASSWORD")
        if interactive and not token and username and password is None and sys.stdin.isatty():
            password = getpass.getpass("AList password: ")
        return cls(base_url, token=token, username=username, password=password, timeout=timeout)

    def _raw_request(self, method, api_path, payload=None, auth=True):
        body = None
        headers = {"Accept": "application/json", "User-Agent": "alist-vidhub-namer/1"}
        headers["Client-Id"] = "alist-vidhub-namer"
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth:
            self.ensure_token()
            headers["Authorization"] = self.token
        request = urllib.request.Request(
            self.base_url + api_path, data=body, headers=headers, method=method
        )
        retryable = {429, 500, 502, 503, 504}
        last_error = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                decoded = json.loads(raw)
                if decoded.get("code") != 200:
                    raise ToolError(
                        "AList API {} failed: code={} message={}".format(
                            api_path, decoded.get("code"), decoded.get("message")
                        )
                    )
                return decoded.get("data")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in retryable or attempt == 4:
                    try:
                        detail = exc.read().decode("utf-8", "replace")
                    except Exception:
                        detail = ""
                    raise ToolError("HTTP {} from {}: {}".format(exc.code, api_path, detail[:500]))
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                time.sleep(min(delay, 15))
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt == 4:
                    raise ToolError("Could not reach AList at {}: {}".format(self.base_url, exc))
                time.sleep(min(2 ** attempt, 15))
            except json.JSONDecodeError as exc:
                raise ToolError("AList returned non-JSON data for {}: {}".format(api_path, exc))
        raise ToolError("AList request failed: {}".format(last_error))

    def ensure_token(self):
        if self.token:
            return
        if not self.username or self.password is None:
            raise ToolError(
                "Set ALIST_TOKEN, or set ALIST_USERNAME and ALIST_PASSWORD. "
                "Do not put secrets on the command line."
            )
        data = self._raw_request(
            "POST",
            "/api/auth/login",
            {"username": self.username, "password": self.password},
            auth=False,
        )
        token = (data or {}).get("token")
        if not token:
            raise ToolError("AList login succeeded without returning a token")
        self.token = token

    def settings(self):
        return self._raw_request("GET", "/api/public/settings", auth=False)

    def list_dir(self, path, refresh=False):
        page = 1
        per_page = 1000
        all_content = []
        write = True
        providers = set()
        while True:
            data = self._raw_request(
                "POST",
                "/api/fs/list",
                {
                    "path": path,
                    "password": "",
                    "page": page,
                    "per_page": per_page,
                    "refresh": bool(refresh),
                },
            ) or {}
            content = data.get("content") or []
            all_content.extend(content)
            write = write and bool(data.get("write", False))
            if data.get("provider"):
                providers.add(str(data["provider"]))
            total = int(data.get("total") or len(all_content))
            if not content or len(all_content) >= total or len(content) < per_page:
                break
            page += 1
        return {"content": all_content, "write": write, "providers": sorted(providers)}

    def rename(self, path, new_name):
        return self._raw_request("POST", "/api/fs/rename", {"path": path, "name": new_name})

    def mkdir(self, path):
        return self._raw_request("POST", "/api/fs/mkdir", {"path": path})

    def move(self, src_dir, dst_dir, names):
        if not isinstance(names, list) or len(names) != 1:
            raise ToolError("Safe move contract requires exactly one name per request")
        return self._raw_request(
            "POST", "/api/fs/move",
            {"src_dir": src_dir, "dst_dir": dst_dir, "names": names},
        )


def read_mode_0600_secret_file(path, label):
    source = Path(path)
    try:
        metadata = source.stat()
        mode = stat.S_IMODE(metadata.st_mode)
    except OSError as exc:
        raise ToolError("Could not read {} metadata: {}".format(label, exc))
    if not source.is_file():
        raise ToolError("{} must be a regular file".format(label))
    if mode & 0o077:
        raise ToolError("{} must not be accessible by group or other users".format(label))
    if metadata.st_size > 16384:
        raise ToolError("{} is unexpectedly large".format(label))
    try:
        value = source.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ToolError("Could not read {}: {}".format(label, exc))
    if not value:
        raise ToolError("{} is empty".format(label))
    return value


class TMDBClient:
    """Small read-only TMDB client for user-supplied application credentials."""

    def __init__(self, token, timeout=30, requests_per_second=5.0, base_url=TMDB_API_BASE_URL):
        if not token:
            raise ToolError("TMDB Read Access Token is empty")
        if requests_per_second <= 0 or requests_per_second > 20:
            raise ToolError("TMDB request rate must be between 0 and 20 requests per second")
        self.token = token
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.minimum_interval = 1.0 / requests_per_second
        self.last_request_at = 0.0
        self._season_cache = {}

    @staticmethod
    def configured():
        return bool(os.environ.get("TMDB_READ_TOKEN") or os.environ.get("TMDB_TOKEN_FILE"))

    @classmethod
    def from_environment(cls, timeout=30, requests_per_second=5.0):
        token = os.environ.get("TMDB_READ_TOKEN", "")
        token_file = os.environ.get("TMDB_TOKEN_FILE", "")
        if token and token_file:
            raise ToolError("Set only one of TMDB_READ_TOKEN or TMDB_TOKEN_FILE")
        if token_file:
            token = read_mode_0600_secret_file(token_file, "TMDB_TOKEN_FILE")
        if not token:
            raise ToolError(
                "Set TMDB_TOKEN_FILE to a mode-0600 file containing your own TMDB API Read "
                "Access Token, or use --resolver none"
            )
        return cls(token, timeout=timeout, requests_per_second=requests_per_second)

    def _wait_for_rate_limit(self):
        remaining = self.minimum_interval - (time.monotonic() - self.last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def request(self, api_path, params=None):
        query = urllib.parse.urlencode(params or {})
        url = self.base_url + api_path + (("?" + query) if query else "")
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + self.token,
            "User-Agent": "alist-vidhub-namer/1",
        }
        retryable = {429, 500, 502, 503, 504}
        for attempt in range(5):
            self._wait_for_rate_limit()
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                self.last_request_at = time.monotonic()
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code not in retryable or attempt == 4:
                    try:
                        detail = exc.read().decode("utf-8", "replace")
                    except Exception:
                        detail = ""
                    raise ToolError("TMDB HTTP {} from {}: {}".format(exc.code, api_path, detail[:500]))
                retry_after = exc.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 2 ** attempt
                except ValueError:
                    delay = 2 ** attempt
                time.sleep(min(max(delay, 0), 15))
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 4:
                    raise ToolError("Could not reach TMDB: {}".format(exc))
                time.sleep(min(2 ** attempt, 15))
            except json.JSONDecodeError as exc:
                raise ToolError("TMDB returned non-JSON data: {}".format(exc))
        raise ToolError("TMDB request failed")

    def check(self):
        return self.request("/3/authentication")

    def search(self, media_type, title, year=None, language="en-US"):
        api_type = "tv" if media_type == "tv" else "movie"
        params = {"query": title, "language": language, "include_adult": "false", "page": 1}
        if year:
            params["first_air_date_year" if api_type == "tv" else "year"] = int(year)
        payload = self.request("/3/search/{}".format(api_type), params)
        return payload.get("results") or []

    def season_episode_titles(self, series_id, season_number, language="en-US"):
        """Map episode_number -> episode name for one season.

        references/naming.md requires the episode title in every TV filename,
        and references/tmdb-api.md pins this to the season endpoint consuming
        only `episode_number` and `name`. Results are cached per (series,
        season) so a batch costs one request per season, not one per file. A
        season TMDB does not have yields an empty map, which callers treat as
        "omit the title", never as a reason to invent one.
        """
        key = (int(series_id), int(season_number))
        if key in self._season_cache:
            return self._season_cache[key]
        try:
            payload = self.request(
                "/3/tv/{}/season/{}".format(key[0], key[1]), {"language": language}
            )
        except ToolError:
            # Shortlisted candidates are probed before the user picks one, so a
            # miss here usually means a wrong candidate rather than a problem.
            # The caller records `tmdb_episode_title_unavailable` when the top
            # candidate comes back empty; that lands in the reviewable plan
            # instead of adding one stderr line per rejected candidate.
            self._season_cache[key] = {}
            return {}
        titles = {}
        for episode in payload.get("episodes") or []:
            number = episode.get("episode_number")
            name = str(episode.get("name") or "").strip()
            # Some limited series were never given individual episode titles in
            # TMDB's own database; it fills the field with "Episode 1", "Episode
            # 2", etc. That duplicates the SxxEyy key already in the filename
            # and carries no information, so it is treated the same as absent.
            if isinstance(number, int) and name and not GENERIC_EPISODE_TITLE_RE.match(name):
                titles[number] = name
        self._season_cache[key] = titles
        return titles


def clean_title(raw):
    raw = unicodedata.normalize("NFKC", raw or "")
    raw = re.sub(r"^[\s._-]+|[\s._-]+$", "", raw)
    tokens = []
    for token in re.split(r"[._]+|\s+", raw):
        token = BRACKET_EDGE_RE.sub("", token).strip(" ._-")
        if token:
            tokens.append(token)
    return " ".join(tokens).strip()


def safe_component(value):
    value = unicodedata.normalize("NFKC", value or "")
    value = INVALID_COMPONENT_RE.sub(" ", value)
    value = SEPARATOR_RE.sub(".", value).strip(" .-")
    value = re.sub(r"\.{2,}", ".", value)
    value = value.rstrip(" .")
    encoded = value.encode("utf-8")
    if len(encoded) > 180:
        encoded = encoded[:180]
        while True:
            try:
                value = encoded.decode("utf-8").rstrip(" .")
                break
            except UnicodeDecodeError:
                encoded = encoded[:-1]
    return value


def suffix_tokens(raw):
    """Split a technical tail into normalized tokens plus the ones left over.

    Returns ``(tokens, unrecognized)``. Dropped silently: embedded-subtitle and
    language markers, site/channel watermarks, and a vague quality word that
    duplicates a resolution already present. These describe container tracks or
    distribution, not the release, and sit outside the documented tag order.

    A token that is neither whitelisted nor known noise is *kept* and also
    reported in ``unrecognized``: it may be a legitimate release group or
    edition, and references/naming.md requires asking rather than stripping.
    Callers surface that as a `review` reason instead of guessing.
    """
    value = unicodedata.normalize("NFKC", raw or "")
    value = value.strip(" ._-")
    value = re.sub(r"[\s_]+", ".", value)
    value = re.sub(r"\.{2,}", ".", value)
    value = INVALID_COMPONENT_RE.sub(".", value)
    # A bracketed site tag can itself contain dots ("ETHEL[EZTVx.to]"), so strip
    # brackets before splitting or the halves survive as separate tokens.
    value = BRACKET_NOISE_RE.sub("", value)
    kept = []
    for token in value.split("."):
        token = CJK_RE.sub("", token).strip(" -")
        token = HANDLE_SUFFIX_RE.sub("", token).strip(" -")
        if not token or LANGUAGE_TAG_RE.match(token) or WATERMARK_RE.match(token):
            continue
        kept.append(token)
    if any(RESOLUTION_RE.match(token) for token in kept):
        kept = [token for token in kept if not VAGUE_QUALITY_RE.match(token)]

    def recognized(index):
        token = kept[index]
        if TECH_TAG_SPELLING.get(token.casefold()) or RECOGNIZED_TAG_RE.match(token):
            return True
        # "H.264-playWEB" arrives split on its own dot; pair the halves.
        if token.casefold() == "h" and index + 1 < len(kept) \
                and re.match(r"(?i)^26[45]\b", kept[index + 1]):
            return True
        return index and kept[index - 1].casefold() == "h" \
            and re.match(r"(?i)^26[45]\b", token) is not None

    # Everything before the first technical tag is the episode title, which is
    # free text and never a whitelist violation. Only the technical region is
    # checked, so an unknown token there can be surfaced for review.
    technical_start = next((i for i in range(len(kept)) if recognized(i)), len(kept))
    tokens = list(kept[:technical_start])
    unrecognized = []
    for index in range(technical_start, len(kept)):
        token = kept[index]
        canonical = TECH_TAG_SPELLING.get(token.casefold())
        if canonical is not None:
            tokens.append(canonical)
            continue
        if not recognized(index):
            unrecognized.append(token)
        tokens.append(token)
    return tokens, unrecognized


def clean_suffix(raw):
    tokens, _ = suffix_tokens(raw)
    return ".".join(tokens).strip(" .-")


def find_episode(stem):
    found = []
    for pattern in EPISODE_PATTERNS:
        match = pattern.search(stem)
        if match:
            found.append(match)
    return min(found, key=lambda match: match.start()) if found else None


def find_year_before(stem, end=None):
    matches = list(YEAR_RE.finditer(stem[:end] if end is not None else stem))
    return matches[-1] if matches else None


def parse_video_name(name, requested_kind="auto", parent_hint=""):
    extension = Path(name).suffix.lower()
    stem = name[: -len(extension)] if extension else name
    episode_match = find_episode(stem)
    kind = "tv" if episode_match else (requested_kind if requested_kind != "auto" else "movie")
    reasons = []
    season = episode = None
    year = None
    parent_fallback = False

    if kind == "tv":
        if not episode_match:
            return {
                "status": "review",
                "confidence": 0.2,
                "reason": ["tv_episode_marker_missing"],
                "media_type": "tv",
                "detected_title": clean_title(stem),
                "year": None,
                "season": None,
                "episode": None,
                "suffix": "",
                "extension": extension,
            }
        season = int(episode_match.group("season"))
        episode = int(episode_match.group("episode"))
        multi_episode = bool(MULTI_EPISODE_TAIL_RE.search(stem[episode_match.end() :]))
        title_region = stem[: episode_match.start()]
        year_match = find_year_before(title_region)
        if year_match:
            year = int(year_match.group("year"))
            title_region = title_region[: year_match.start()]
        title = clean_title(title_region)
        if not title:
            title = clean_title(parent_hint)
            parent_fallback = bool(title)
            reasons.append("title_inferred_from_parent")
        suffix_parts, unknown_tags = suffix_tokens(stem[episode_match.end() :])
        suffix = ".".join(suffix_parts).strip(" .-")
        confidence = 0.68 if parent_fallback else 0.86
        if not title:
            reasons.append("title_missing")
            confidence = 0.15
        if multi_episode:
            reasons.append("multi_episode_pattern_requires_review")
            confidence = min(confidence, 0.5)
    else:
        year_match = find_year_before(stem)
        tech_match = TECH_RE.search(stem)
        title_end = len(stem)
        suffix_start = len(stem)
        if year_match:
            year = int(year_match.group("year"))
            title_end = year_match.start()
            suffix_start = year_match.end()
        elif tech_match:
            title_end = tech_match.start()
            suffix_start = tech_match.start()
        title = clean_title(stem[:title_end])
        suffix_parts, unknown_tags = suffix_tokens(stem[suffix_start:])
        suffix = ".".join(suffix_parts).strip(" .-")
        confidence = 0.78 if year else 0.58
        if tech_match:
            confidence += 0.04
        if not title:
            title = clean_title(parent_hint)
            parent_fallback = bool(title)
            reasons.append("title_inferred_from_parent")
            confidence = 0.5 if title else 0.15
        if not year:
            reasons.append("release_year_missing")

    if unknown_tags:
        # naming.md: an unfamiliar tail token may be a real release group or
        # edition. Keep it, but never auto-execute on it — ask instead.
        reasons.append("unrecognized_tail_token:" + ",".join(sorted(set(unknown_tags))))
        confidence = min(confidence, 0.5)

    return {
        "status": "ready" if confidence >= 0.85 else "review",
        "confidence": round(min(confidence, 1.0), 3),
        "reason": reasons,
        "media_type": kind,
        "detected_title": title,
        "year": year,
        "season": season,
        "episode": episode,
        "suffix": suffix,
        "extension": extension,
    }


def build_name(parsed, canonical_title=None, canonical_year=None):
    title = safe_component(canonical_title or parsed["detected_title"])
    parts = [title]
    if parsed["media_type"] == "movie":
        year = canonical_year or parsed.get("year")
        if year:
            parts.append(str(year))
    if parsed["media_type"] == "tv" and parsed.get("season") is not None:
        parts.append("S{:02d}E{:02d}".format(parsed["season"], parsed["episode"]))
    if parsed.get("suffix"):
        parts.append(parsed["suffix"])
    stem = ".".join(part for part in parts if part)
    return stem + parsed.get("extension", "")


def normalized_identity(value):
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(character for character in value if character.isalnum())


def contains_cjk(value):
    return any(
        "\u3400" <= character <= "\u4dbf" or "\u4e00" <= character <= "\u9fff"
        for character in value or ""
    )


def tmdb_result_to_candidate(media_type, result, query_title, query_year, rank):
    if media_type == "tv":
        title = str(result.get("name") or "").strip()
        original_title = str(result.get("original_name") or "").strip()
        date_value = str(result.get("first_air_date") or "")
        scope = "tv"
    else:
        title = str(result.get("title") or "").strip()
        original_title = str(result.get("original_title") or "").strip()
        date_value = str(result.get("release_date") or "")
        scope = "movie"
    try:
        tmdb_id = int(result.get("id"))
    except (TypeError, ValueError):
        return None
    candidate_year = int(date_value[:4]) if re.match(r"^\d{4}", date_value) else None
    query_key = normalized_identity(query_title)
    title_keys = [normalized_identity(title), normalized_identity(original_title)]
    title_keys = [value for value in title_keys if value]
    if not query_key or not title_keys:
        title_score = 0.0
        exact_title = False
    else:
        exact_title = query_key in title_keys
        title_score = 0.65 if exact_title else 0.55 * max(
            SequenceMatcher(None, query_key, candidate).ratio() for candidate in title_keys
        )
    if query_year and candidate_year == int(query_year):
        year_score = 0.28
        exact_year = True
    elif not query_year or candidate_year is None:
        year_score = 0.0
        exact_year = False
    elif abs(candidate_year - int(query_year)) == 1:
        year_score = 0.08
        exact_year = False
    else:
        year_score = 0.0
        exact_year = False
    rank_score = max(0.0, 0.05 - 0.01 * rank)
    score = round(min(title_score + year_score + rank_score, 0.99), 3)
    canonical_title = title or original_title
    return {
        "tmdb_id": tmdb_id,
        "media_type": media_type,
        "title": canonical_title,
        "original_title": original_title,
        "year": candidate_year,
        "score": score,
        "exact_title": exact_title,
        "exact_year": exact_year,
        "url": "https://www.themoviedb.org/{}/{}".format(scope, tmdb_id),
    }


def build_tmdb_suggestion(entry, candidate, episode_title=None):
    parsed = parse_video_name(
        entry["old_name"], entry.get("media_type", "auto"),
        parent_hint=posixpath.basename(entry.get("directory", "").rstrip("/")),
    )
    title = candidate.get("title") or entry.get("detected_title")
    extension = parsed.get("extension", "")
    parts = [safe_component(title)]
    suffix = parsed.get("suffix") or ""
    if entry.get("media_type") == "movie":
        # Preserve the filename's explicit identity year. TMDB may expose a later
        # wide-release date for a film that premiered at a festival the year before.
        year = entry.get("year") or candidate.get("year")
        if year:
            parts.append(str(year))
        parts.append("{tmdb-%s}" % candidate["tmdb_id"])
    elif parsed.get("season") is not None:
        parts.append("S{:02d}E{:02d}".format(parsed["season"], parsed["episode"]))
        if episode_title:
            canonical_episode = safe_component(episode_title)
            parts.append(canonical_episode)
            # The source may already carry a title, canonical or localized, in
            # the same slot. Drop that leading run so the TMDB name does not
            # land next to a stale duplicate of itself.
            suffix = drop_leading_episode_title(suffix, canonical_episode)
    if suffix:
        parts.append(suffix)
    return ".".join(part for part in parts if part) + extension


def drop_leading_episode_title(suffix, canonical_episode):
    """Strip the source's own copy of the episode title from the front of a tail.

    Compares whole leading runs against the canonical title rather than walking
    token by token, because an episode title can contain tokens that look
    technical on their own: "Demon 79" ends in a bare number, and stopping at
    it would leave "79" behind to be appended twice.

    A leading run that does not match is left alone. It may be a real tag the
    whitelist does not know yet ("1080p-YYeTs"), and dropping tags to make room
    for a title loses information that cannot be recovered from the target name.
    """
    if not suffix or not canonical_episode:
        return suffix
    tokens = suffix.split(".")
    wanted = normalized_identity(canonical_episode)
    for length in range(len(tokens), 0, -1):
        if normalized_identity(".".join(tokens[:length])) == wanted:
            return ".".join(tokens[length:])
    return suffix


def resolve_tmdb_entries(client, entries, language="en-US", max_candidates=3):
    if not 1 <= max_candidates <= 10:
        raise ToolError("--max-candidates must be between 1 and 10")
    counts = Counter()
    for entry in entries:
        if entry.get("media_type") not in {"movie", "tv"}:
            continue
        title = entry.get("detected_title")
        if not title:
            entry["tmdb_resolution"] = {"status": "unresolved", "reason": "title_missing"}
            counts["unresolved"] += 1
            continue
        search_languages = [language]
        if contains_cjk(title) and language.casefold() != "zh-cn":
            search_languages.append("zh-CN")
        candidates_by_id = {}
        for search_language in search_languages:
            results = client.search(
                entry["media_type"], title, entry.get("year"), search_language
            )
            for rank, result in enumerate(results):
                candidate = tmdb_result_to_candidate(
                    entry["media_type"], result, title, entry.get("year"), rank
                )
                if candidate is None:
                    continue
                existing = candidates_by_id.get(candidate["tmdb_id"])
                if existing is None:
                    candidates_by_id[candidate["tmdb_id"]] = candidate
                    continue
                # Keep the canonical title from the requested output language,
                # but use translated-title matching evidence from zh-CN.
                existing["score"] = max(existing["score"], candidate["score"])
                existing["exact_title"] = existing["exact_title"] or candidate["exact_title"]
                existing["exact_year"] = existing["exact_year"] or candidate["exact_year"]
        candidates = list(candidates_by_id.values())
        candidates.sort(key=lambda value: value["score"], reverse=True)
        candidates = candidates[:max_candidates]
        # Build suggestions only for the shortlist: the season lookup below is a
        # network call, and a candidate that did not survive ranking is not
        # worth one. The client caches per (series, season), so a whole season
        # of files costs one request.
        season = entry.get("season")
        episode = entry.get("episode")
        want_episode_title = (
            entry.get("media_type") == "tv" and season is not None and episode is not None
        )
        for candidate in candidates:
            episode_title = None
            if want_episode_title:
                episode_title = client.season_episode_titles(
                    candidate["tmdb_id"], season, language
                ).get(episode)
                candidate["episode_title"] = episode_title
            candidate["suggested_new_name"] = build_tmdb_suggestion(
                entry, candidate, episode_title
            )
        entry["tmdb_candidates"] = candidates
        if want_episode_title and candidates and not candidates[0].get("episode_title"):
            entry.setdefault("reason", []).append("tmdb_episode_title_unavailable")
        if not candidates:
            status = "not_found"
            reason = "tmdb_no_candidates"
        else:
            top = candidates[0]
            runner_up = candidates[1]["score"] if len(candidates) > 1 else 0.0
            if top["exact_title"] and top["exact_year"] and top["score"] >= 0.9 \
                    and top["score"] - runner_up >= 0.1:
                status = "proposed"
                reason = "tmdb_exact_candidate_requires_confirmation"
            else:
                status = "ambiguous"
                reason = "tmdb_candidates_require_review"
        entry["tmdb_resolution"] = {"status": status, "reason": reason}
        entry.setdefault("reason", []).append(reason)
        if entry.get("status") != "conflict":
            entry["status"] = "review"
            entry["confidence"] = min(float(entry.get("confidence", 0)), 0.84)
        counts[status] += 1
    return dict(counts)


def walk_alist(client, root, max_files, refresh=False, delay=0.05):
    queue = deque([root])
    files = []
    directory_names = {}
    directory_meta = {}
    seen_dirs = set()
    while queue:
        directory = queue.popleft()
        if directory in seen_dirs:
            continue
        seen_dirs.add(directory)
        result = client.list_dir(directory, refresh=refresh)
        content = result["content"]
        names = {str(item.get("name", "")) for item in content}
        directory_names[directory] = names
        directory_meta[directory] = {
            "write": result["write"],
            "providers": result["providers"],
        }
        for item in content:
            name = str(item.get("name", ""))
            if not name or "/" in name:
                continue
            full_path = join_path(directory, name)
            if item.get("is_dir"):
                queue.append(full_path)
            else:
                record = dict(item)
                record["full_path"] = full_path
                record["directory"] = directory
                files.append(record)
                if len(files) > max_files:
                    raise ToolError("Scan exceeded --max-files={}".format(max_files))
        if delay:
            time.sleep(delay)
    return files, directory_names, directory_meta


def add_sidecar_entries(entries, files):
    videos_by_dir = defaultdict(list)
    for entry in entries:
        if entry["media_type"] in {"movie", "tv"}:
            videos_by_dir[entry["directory"]].append(entry)
    for item in files:
        name = item["name"]
        extension = Path(name).suffix.lower()
        if extension not in SUBTITLE_EXTENSIONS:
            continue
        stem = name[: -len(extension)]
        candidates = []
        for video in videos_by_dir.get(item["directory"], []):
            video_ext = Path(video["old_name"]).suffix
            video_stem = video["old_name"][: -len(video_ext)] if video_ext else video["old_name"]
            if stem == video_stem or stem.startswith(video_stem + ".") or stem.startswith(video_stem + "_"):
                candidates.append((len(video_stem), video, stem[len(video_stem) :]))
        if not candidates:
            continue
        _, video, remainder = max(candidates, key=lambda value: value[0])
        target_video_ext = Path(video["new_name"]).suffix
        target_video_stem = (
            video["new_name"][: -len(target_video_ext)] if target_video_ext else video["new_name"]
        )
        new_name = target_video_stem + remainder + extension
        entries.append(
            {
                "old_path": item["full_path"],
                "directory": item["directory"],
                "old_name": name,
                "new_name": new_name,
                "media_type": "subtitle",
                "source_video": video["old_path"],
                "detected_title": video["detected_title"],
                "year": video.get("year"),
                "season": video.get("season"),
                "episode": video.get("episode"),
                "size": item.get("size"),
                "modified": item.get("modified"),
                "confidence": video["confidence"],
                "status": video["status"],
                "reason": list(video.get("reason") or []) + ["paired_subtitle"],
            }
        )


def mark_conflicts(entries, directory_names):
    by_dir = defaultdict(list)
    for entry in entries:
        by_dir[entry["directory"]].append(entry)
    for directory, group in by_dir.items():
        target_counts = Counter(entry["new_name"].casefold() for entry in group)
        old_to_target = {entry["old_name"].casefold(): entry["new_name"].casefold() for entry in group}
        existing = {name.casefold() for name in directory_names.get(directory, set())}
        for entry in group:
            old_key = entry["old_name"].casefold()
            target_key = entry["new_name"].casefold()
            if entry["new_name"] == entry["old_name"]:
                if entry["status"] == "ready":
                    entry["status"] = "skip"
                    entry["reason"].append("already_compliant")
                else:
                    entry["reason"].append("already_normalized_but_requires_review")
                continue
            if target_counts[target_key] > 1:
                entry["status"] = "conflict"
                entry["reason"].append("duplicate_target_in_plan")
                continue
            target_is_vacated = target_key in old_to_target and old_to_target[target_key] != target_key
            if target_key in existing and target_key != old_key and not target_is_vacated:
                entry["status"] = "conflict"
                entry["reason"].append("target_already_exists")


def summarize(entries):
    status = Counter(entry["status"] for entry in entries)
    media = Counter(entry["media_type"] for entry in entries)
    return {"total": len(entries), "by_status": dict(status), "by_media_type": dict(media)}


def write_csv(path, entries):
    columns = [
        "status", "confidence", "media_type", "old_path", "new_name", "detected_title",
        "year", "season", "episode", "tmdb_id", "tmdb_scope", "reason",
    ]
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for entry in entries:
            row = dict(entry)
            row["reason"] = ",".join(entry.get("reason") or [])
            writer.writerow(row)


def command_tmdb_setup(args):
    if not sys.stdin.isatty():
        raise ToolError("tmdb-setup must be run interactively in the user's terminal")
    if not args.accept_terms:
        raise ToolError(
            "Read the current TMDB API terms, then repeat with --accept-terms if you agree"
        )
    if os.environ.get("TMDB_READ_TOKEN") or os.environ.get("TMDB_TOKEN_FILE"):
        raise ToolError("Unset TMDB_READ_TOKEN and TMDB_TOKEN_FILE before creating a new token file")
    destination = Path(args.token_file)
    if destination.exists():
        raise ToolError("TMDB token file already exists; choose another path")
    token = getpass.getpass("TMDB API Read Access Token: ").strip()
    client = TMDBClient(token, timeout=args.timeout, requests_per_second=args.tmdb_rate)
    client.check()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(token)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            destination.unlink()
        except OSError:
            pass
        raise
    finally:
        token = None
        client.token = ""
    print("TMDB token verified and written with mode 0600 to {}".format(destination))
    print("Set TMDB_TOKEN_FILE to this path. Never add it to Git or a shared Skill archive.")


def command_tmdb_check(args):
    client = TMDBClient.from_environment(args.timeout, args.tmdb_rate)
    payload = client.check()
    print(json.dumps({
        "authenticated": bool(payload.get("success", True)),
        "api_base_url": TMDB_API_BASE_URL,
        "requests_per_second": args.tmdb_rate,
    }, ensure_ascii=False, indent=2))


def command_tmdb_resolve(args):
    plan = load_json(args.plan)
    validate_plan(plan)
    output_path = Path(args.output).resolve()
    if output_path == Path(args.plan).resolve():
        raise ToolError("--output must not overwrite the source plan")
    client = TMDBClient.from_environment(args.timeout, args.tmdb_rate)
    resolution = resolve_tmdb_entries(
        client, plan["entries"], language=args.language,
        max_candidates=args.max_candidates,
    )
    parent_plan_id = plan.get("plan_id")
    plan["plan_id"] = uuid.uuid4().hex
    plan["parent_plan_id"] = parent_plan_id
    plan["tmdb_resolved_at"] = utc_now()
    plan["metadata_resolver"] = {
        "kind": "tmdb_byok",
        "language": args.language,
        "resolution": resolution,
    }
    plan["summary"] = summarize(plan["entries"])
    atomic_json_write(args.output, plan)
    print(json.dumps(resolution, ensure_ascii=False, indent=2))
    for entry in plan["entries"]:
        candidates = entry.get("tmdb_candidates") or []
        if not candidates:
            continue
        top = candidates[0]
        print("{} -> {} [{}] {}".format(
            entry["old_path"], top["suggested_new_name"], top["tmdb_id"], top["url"]
        ))
    print("TMDB candidate plan written to {}".format(args.output))


def command_check(args):
    client = AListClient.from_environment(args.timeout, args.interactive_auth)
    settings = client.settings()
    listing = client.list_dir(args.path, refresh=False)
    payload = {
        "alist_url": client.base_url,
        "version": settings.get("version"),
        "path": args.path,
        "write": listing["write"],
        "providers": listing["providers"],
        "item_count": len(listing["content"]),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not listing["write"]:
        raise ToolError("The selected path is read-only; apply/rollback will not be allowed")


def validate_folder_target(name):
    if not isinstance(name, str) or not name or name.startswith("."):
        raise ToolError("Unsafe folder target name: {}".format(name))
    if name in {".", ".."} or "/" in name or INVALID_COMPONENT_RE.search(name):
        raise ToolError("Folder target contains cross-platform unsafe characters")
    if len(name.encode("utf-8")) > 255:
        raise ToolError("Folder target exceeds 255 UTF-8 bytes")


def command_folder_plan(args):
    if not args.path.startswith("/") or args.path == "/":
        raise ToolError("--path must be a narrow, non-root absolute AList path")
    mappings = load_json(args.mapping_file)
    if not isinstance(mappings, list) or not 1 <= len(mappings) <= 20:
        raise ToolError("Folder canary mapping must be a JSON list containing 1-20 entries")
    normalized = []
    for mapping in mappings:
        if not isinstance(mapping, dict) or set(mapping) != {"old_name", "new_name"}:
            raise ToolError("Each folder mapping must contain only old_name and new_name")
        old_name = mapping["old_name"]
        new_name = mapping["new_name"]
        if not isinstance(old_name, str) or not old_name or "/" in old_name \
                or old_name in {".", ".."}:
            raise ToolError("Unsafe folder source name: {}".format(old_name))
        validate_folder_target(new_name)
        if old_name == new_name:
            raise ToolError("Folder mapping does not require a rename: {}".format(old_name))
        normalized.append((old_name, new_name))
    old_keys = [old.casefold() for old, _ in normalized]
    target_keys = [new.casefold() for _, new in normalized]
    if len(set(old_keys)) != len(old_keys):
        raise ToolError("Folder source names must be unique")
    if len(set(target_keys)) != len(target_keys):
        raise ToolError("Folder target names must be unique")

    client = AListClient.from_environment(args.timeout, args.interactive_auth)
    settings = client.settings()
    listing = client.list_dir(args.path, refresh=True)
    if not listing["write"]:
        raise ToolError("The selected folder root is read-only")
    items = {str(item.get("name", "")): item for item in listing["content"]}
    existing_folded = {name.casefold() for name in items}
    planned_old = set(old_keys)
    entries = []
    for old_name, new_name in normalized:
        item = items.get(old_name)
        if item is None:
            raise ToolError("Folder source changed or disappeared: {}".format(join_path(args.path, old_name)))
        if not item.get("is_dir"):
            raise ToolError("Folder mapping source is not a directory: {}".format(old_name))
        target_key = new_name.casefold()
        if target_key in existing_folded and target_key not in planned_old:
            raise ToolError("Folder target already exists: {}".format(join_path(args.path, new_name)))
        entries.append({
            "old_path": join_path(args.path, old_name),
            "directory": args.path,
            "old_name": old_name,
            "new_name": new_name,
            "media_type": "folder",
            "confidence": 1.0,
            "status": "ready",
            "reason": ["exact_folder_mapping_confirmed"],
        })
    plan = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": uuid.uuid4().hex,
        "created_at": utc_now(),
        "plan_kind": "folder_rename",
        "alist_url": client.base_url,
        "alist_version": settings.get("version"),
        "root_path": args.path,
        "writable": True,
        "providers": listing["providers"],
        "ready_threshold": 1.0,
        "selection": {"kind": "folder_canary", "folder_count": len(entries)},
        "summary": summarize(entries),
        "entries": entries,
    }
    validate_plan(plan)
    atomic_json_write(args.output, plan)
    print("Folder plan: {} direct child directories".format(len(entries)))
    for entry in entries:
        print("{} -> {}".format(entry["old_path"], entry["new_name"]))
    print("Folder plan written to {}".format(args.output))


def validate_organize_plan(plan):
    if plan.get("schema_version") != SCHEMA_VERSION or plan.get("plan_kind") != "organize_move":
        raise ToolError("Invalid or unsupported organize plan")
    root = plan.get("root_path")
    destination_name = plan.get("destination_name")
    destination_path = plan.get("destination_path")
    entries = plan.get("entries")
    if not isinstance(root, str) or not root.startswith("/") or root == "/":
        raise ToolError("Organize plan root_path must be a narrow absolute path")
    if posixpath.normpath(root) != root:
        raise ToolError("Organize plan root_path is not normalized")
    if not isinstance(destination_name, str) or not destination_name or destination_name.startswith("/"):
        raise ToolError("Organize destination_name must be a non-empty relative path")
    for segment in destination_name.split("/"):
        validate_folder_target(segment)
    if destination_path != posixpath.normpath(join_path(root, destination_name)):
        raise ToolError("Organize destination_path does not match root_path/destination_name")
    if not path_is_within(root, destination_path) or destination_path == root:
        raise ToolError("Organize destination must be within root_path")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 20:
        raise ToolError("Organize plan must contain 1-20 exact folders")
    if plan.get("folder_count") != len(entries):
        raise ToolError("Organize plan folder_count does not match entries")
    seen = set()
    target_seen = set()
    required = {"name", "source_dir", "source_path", "target_dir", "target_path"}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != required:
            raise ToolError("Invalid organize plan entry")
        name = entry["name"]
        validate_folder_target(name)
        source_dir = entry["source_dir"]
        if not isinstance(source_dir, str) or not source_dir.startswith("/") \
                or posixpath.normpath(source_dir) != source_dir:
            raise ToolError("Organize source_dir must be a normalized absolute path")
        if not path_is_within(root, source_dir):
            raise ToolError("Organize source_dir escapes root_path")
        if entry["source_path"] != join_path(source_dir, name):
            raise ToolError("Organize source path does not match source_dir/name")
        if entry["source_path"].casefold() in seen:
            raise ToolError("Organize source paths must be unique")
        seen.add(entry["source_path"].casefold())
        if entry["target_dir"] != destination_path \
                or entry["target_path"] != join_path(destination_path, name):
            raise ToolError("Organize target path does not match destination/name")
        target_key = entry["target_path"].casefold()
        if target_key in target_seen:
            raise ToolError("Organize target names must be unique")
        target_seen.add(target_key)
        if not path_is_within(root, entry["source_path"]) \
                or not path_is_within(root, entry["target_path"]):
            raise ToolError("Organize plan entry escapes root_path")
    for path_a, path_b in itertools.combinations(
        (entry["source_path"] for entry in entries), 2
    ):
        if path_is_within(path_a, path_b) or path_is_within(path_b, path_a):
            raise ToolError("Organize plan entries overlap: {} / {}".format(path_a, path_b))


def resolve_organize_relative_path(root, raw, label="path"):
    """Resolve a --folder/--destination value into (parent_dir, name, full_path).

    A bare name (no "/") is a direct child of root, preserving prior
    behavior. A relative path with "/" segments identifies a location nested
    under root at any depth; every segment is validated the same way a
    direct-child name would be, and traversal outside root is rejected by
    construction (no ".", "..", or absolute segments are accepted).
    """
    if not isinstance(raw, str) or not raw or raw.startswith("/"):
        raise ToolError("Organize {} must be a non-empty relative path: {}".format(label, raw))
    segments = raw.split("/")
    for segment in segments:
        validate_folder_target(segment)
    name = segments[-1]
    relative_dir = "/".join(segments[:-1])
    parent_dir = join_path(root, relative_dir) if relative_dir else root
    full_path = join_path(parent_dir, name)
    return parent_dir, name, full_path


def parse_organize_folder_arg(root, raw):
    return resolve_organize_relative_path(root, raw, label="--folder value")


def command_organize_plan(args):
    root = args.path
    if not isinstance(root, str) or not root.startswith("/") or root == "/" \
            or posixpath.normpath(root) != root:
        raise ToolError("--path must be a normalized, narrow, non-root absolute AList path")
    destination_parent, destination_leaf, destination_path = resolve_organize_relative_path(
        root, args.destination, label="--destination"
    )
    destination_is_nested = destination_parent != root
    raw_folders = list(dict.fromkeys(args.folder))
    if len(raw_folders) != len(args.folder):
        raise ToolError("--folder values must be unique")
    if not 1 <= len(raw_folders) <= 20:
        raise ToolError("Organize plan requires 1-20 exact source folders")
    resolved = []
    for raw in raw_folders:
        source_dir, name, source_path = parse_organize_folder_arg(root, raw)
        if not path_is_within(root, source_dir):
            raise ToolError("Organize source escapes root_path: {}".format(raw))
        if source_path == destination_path:
            raise ToolError("A source folder cannot be the destination folder")
        if path_is_within(source_path, destination_path):
            raise ToolError("Destination cannot be nested inside a source folder: {}".format(raw))
        resolved.append((source_dir, name, source_path))
    source_paths = [item[2] for item in resolved]
    for i, path_a in enumerate(source_paths):
        for path_b in source_paths[i + 1:]:
            if path_a == path_b:
                raise ToolError("--folder values must be unique")
            if path_is_within(path_a, path_b) or path_is_within(path_b, path_a):
                raise ToolError(
                    "Selected organize folders overlap; one contains the other: {} / {}".format(
                        path_a, path_b
                    )
                )

    client = AListClient.from_environment(args.timeout, args.interactive_auth)
    settings = client.settings()
    root_listing = client.list_dir(root, refresh=True)
    if not root_listing["write"]:
        raise ToolError("The selected organize root is read-only")
    listing_cache = {root: root_listing}

    def cached_listing(path):
        if path not in listing_cache:
            listing_cache[path] = client.list_dir(path, refresh=True)
        return listing_cache[path]

    destination_parent_listing = cached_listing(destination_parent)
    destination_parent_items = {
        str(item.get("name", "")): item for item in destination_parent_listing["content"]
    }
    destination_item = {name.casefold(): item for name, item in destination_parent_items.items()}.get(
        destination_leaf.casefold()
    )
    if destination_item is None and destination_is_nested:
        raise ToolError(
            "Nested organize destination does not exist: {}. "
            "This Skill only creates a single-level destination; "
            "create the nested destination first.".format(destination_path)
        )
    destination_names = set()
    if destination_item is not None:
        if not destination_item.get("is_dir"):
            raise ToolError("Organize destination exists but is not a directory")
        destination_listing = client.list_dir(destination_path, refresh=True)
        if not destination_listing["write"]:
            raise ToolError("The organize destination is read-only")
        destination_names = {str(item.get("name", "")).casefold()
                             for item in destination_listing["content"]}
    entries = []
    for source_dir, name, source_path in resolved:
        source_listing = cached_listing(source_dir)
        if not source_listing["write"]:
            raise ToolError("The organize source directory is read-only: {}".format(source_dir))
        source_items = {str(item.get("name", "")): item for item in source_listing["content"]}
        item = source_items.get(name)
        if item is None:
            raise ToolError("Source folder changed or disappeared: {}".format(source_path))
        if not item.get("is_dir"):
            raise ToolError("Organize source is not a directory: {}".format(source_path))
        if name.casefold() in destination_names:
            raise ToolError("Destination already contains: {}".format(join_path(destination_path, name)))
        entries.append({
            "name": name,
            "source_dir": source_dir,
            "source_path": source_path,
            "target_dir": destination_path,
            "target_path": join_path(destination_path, name),
        })
    target_keys = [entry["target_path"].casefold() for entry in entries]
    if len(set(target_keys)) != len(target_keys):
        raise ToolError("Organize plan target names must be unique")
    plan = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": uuid.uuid4().hex,
        "created_at": utc_now(),
        "plan_kind": "organize_move",
        "alist_url": client.base_url,
        "alist_version": settings.get("version"),
        "root_path": root,
        "destination_name": args.destination,
        "destination_path": destination_path,
        "create_destination": destination_item is None,
        "writable": True,
        "providers": root_listing["providers"],
        "folder_count": len(entries),
        "entries": entries,
    }
    validate_organize_plan(plan)
    atomic_json_write(args.output, plan)
    print("Organize plan: {} folders -> {}".format(len(entries), destination_path))
    print("Create destination: {}".format("yes" if plan["create_destination"] else "no"))
    for entry in entries:
        print("{} -> {}".format(entry["source_path"], entry["target_path"]))
    print("Organize plan written to {}".format(args.output))


def make_organize_journal(plan, journal_path):
    journal = {
        "schema_version": SCHEMA_VERSION,
        "journal_kind": "organize_move",
        "run_id": uuid.uuid4().hex,
        "plan_id": plan.get("plan_id"),
        "alist_url": plan.get("alist_url"),
        "root_path": plan["root_path"],
        "destination_name": plan["destination_name"],
        "destination_path": plan["destination_path"],
        "destination_created": False,
        "created_at": utc_now(),
        "status": "running",
        "entries": [dict(entry, state="pending", error=None) for entry in plan["entries"]],
        "rollback_note": None,
    }
    atomic_json_write(journal_path, journal)
    return journal


def validate_organize_journal(journal):
    if journal.get("schema_version") != SCHEMA_VERSION \
            or journal.get("journal_kind") != "organize_move":
        raise ToolError("Invalid or unsupported organize journal")
    entries = journal.get("entries")
    if not isinstance(entries, list):
        raise ToolError("Invalid organize journal entries")
    plan_shape = {
        "schema_version": journal.get("schema_version"),
        "plan_kind": "organize_move",
        "root_path": journal.get("root_path"),
        "destination_name": journal.get("destination_name"),
        "destination_path": journal.get("destination_path"),
        "folder_count": len(entries) if isinstance(entries, list) else None,
        "entries": [],
    }
    allowed_states = {"pending", "moved", "restored", "restore_failed", "rolled_back", "rollback_failed"}
    required = {"name", "source_dir", "source_path", "target_dir", "target_path", "state", "error"}
    for record in entries:
        if not isinstance(record, dict) or not required.issubset(record):
            raise ToolError("Invalid organize journal entry")
        if record.get("state") not in allowed_states:
            raise ToolError("Invalid organize journal state")
        plan_shape["entries"].append({key: record[key] for key in (
            "name", "source_dir", "source_path", "target_dir", "target_path"
        )})
    validate_organize_plan(plan_shape)


def restore_organize_after_failure(client, journal, journal_path, delay):
    journal["status"] = "restore_after_failure"
    atomic_json_write(journal_path, journal)
    for record in reversed(journal["entries"]):
        if record["state"] != "moved":
            continue
        try:
            client.move(record["target_dir"], record["source_dir"], [record["name"]])
            record["state"] = "restored"
            record["error"] = None
        except Exception as exc:
            record["state"] = "restore_failed"
            record["error"] = str(exc)
        atomic_json_write(journal_path, journal)
        time.sleep(delay)
    restored = all(record["state"] in {"pending", "restored"} for record in journal["entries"])
    journal["status"] = "restored" if restored else "manual_recovery_required"
    if journal.get("destination_created"):
        journal["rollback_note"] = "Empty destination retained; this Skill never deletes directories."
    atomic_json_write(journal_path, journal)


def command_organize_apply(args):
    plan = load_json(args.plan)
    validate_organize_plan(plan)
    print("Ready to organize {} folders into {}".format(plan["folder_count"], plan["destination_path"]))
    print("Create destination: {}".format("yes" if plan.get("create_destination") else "no"))
    for entry in plan["entries"]:
        print("{} -> {}".format(entry["source_path"], entry["target_path"]))
    if not args.execute:
        print("Dry run only. Re-run with --execute --confirm-root '{}' --confirm-folder-count {}".format(
            plan["root_path"], plan["folder_count"]
        ))
        return
    if args.confirm_root != plan["root_path"]:
        raise ToolError("--confirm-root must exactly match {}".format(plan["root_path"]))
    if args.confirm_folder_count != plan["folder_count"]:
        raise ToolError("--confirm-folder-count must exactly match {}".format(plan["folder_count"]))
    if not plan.get("writable"):
        raise ToolError("Organize plan reports a read-only path")
    journal_path = args.journal or str(Path(args.plan).with_suffix(".organize-journal.json"))
    if Path(journal_path).exists():
        raise ToolError("Journal already exists; choose another --journal path")
    client = AListClient.from_environment(args.timeout, args.interactive_auth)
    if plan.get("alist_url") and client.base_url != plan["alist_url"]:
        raise ToolError("ALIST_URL does not match the organize plan's alist_url")

    root_listing = client.list_dir(plan["root_path"], refresh=True)
    if not root_listing["write"]:
        raise ToolError("The organize root is read-only")
    listing_cache = {plan["root_path"]: root_listing}
    destination_parent = parent_path(plan["destination_path"])
    destination_leaf = posixpath.basename(plan["destination_path"])
    destination_is_nested = destination_parent != plan["root_path"]
    if destination_parent not in listing_cache:
        listing_cache[destination_parent] = client.list_dir(destination_parent, refresh=True)
    destination_parent_listing = listing_cache[destination_parent]
    destination_parent_items = {
        str(item.get("name", "")): item for item in destination_parent_listing["content"]
    }
    destination_item = {name.casefold(): item for name, item in destination_parent_items.items()}.get(
        destination_leaf.casefold()
    )
    if destination_item is None and destination_is_nested:
        raise ToolError("Nested organize destination changed or disappeared: {}".format(
            plan["destination_path"]
        ))
    for entry in plan["entries"]:
        source_dir = entry["source_dir"]
        if source_dir not in listing_cache:
            listing_cache[source_dir] = client.list_dir(source_dir, refresh=True)
        source_listing = listing_cache[source_dir]
        if not source_listing["write"]:
            raise ToolError("The organize source directory is read-only: {}".format(source_dir))
        source_items = {str(item.get("name", "")): item for item in source_listing["content"]}
        item = source_items.get(entry["name"])
        if item is None or not item.get("is_dir"):
            raise ToolError("Source folder changed or disappeared: {}".format(entry["source_path"]))
    if destination_item is not None and not destination_item.get("is_dir"):
        raise ToolError("Organize destination exists but is not a directory")
    if destination_item is not None:
        destination_listing = client.list_dir(plan["destination_path"], refresh=True)
        occupied = {str(item.get("name", "")).casefold() for item in destination_listing["content"]}
        for entry in plan["entries"]:
            if entry["name"].casefold() in occupied:
                raise ToolError("Destination target is occupied: {}".format(entry["target_path"]))

    journal = make_organize_journal(plan, journal_path)
    try:
        if destination_item is None:
            client.mkdir(plan["destination_path"])
            journal["destination_created"] = True
            atomic_json_write(journal_path, journal)
            time.sleep(args.move_delay)
        for record in journal["entries"]:
            client.move(record["source_dir"], record["target_dir"], [record["name"]])
            record["state"] = "moved"
            atomic_json_write(journal_path, journal)
            time.sleep(args.move_delay)
    except Exception as exc:
        eprint("ERROR: organize apply failed; attempting automatic restore: {}".format(exc))
        restore_organize_after_failure(client, journal, journal_path, args.move_delay)
        raise ToolError("Organize apply failed. Inspect {} (status={})".format(
            journal_path, journal["status"]
        ))
    journal["status"] = "complete"
    journal["completed_at"] = utc_now()
    atomic_json_write(journal_path, journal)
    try:
        update_state_after_organize(args, journal, reverse=False)
    except Exception as exc:
        eprint("WARNING: Remote organization succeeded but state update failed: {}".format(exc))
    print("Organized {} folders. Journal: {}".format(plan["folder_count"], journal_path))


def command_organize_rollback(args):
    journal = load_json(args.journal)
    validate_organize_journal(journal)
    candidates = [record for record in reversed(journal["entries"])
                  if record["state"] in {"moved", "restore_failed", "rollback_failed"}]
    print("Organize rollback would restore {} folders to {}".format(
        len(candidates), journal["root_path"]
    ))
    if journal.get("destination_created"):
        print("The empty destination directory will be retained; delete endpoints are never used.")
    if not args.execute:
        print("Dry run only. Re-run with --execute --confirm-root '{}'".format(journal["root_path"]))
        return
    if args.confirm_root != journal["root_path"]:
        raise ToolError("--confirm-root must exactly match {}".format(journal["root_path"]))
    client = AListClient.from_environment(args.timeout, args.interactive_auth)
    if journal.get("alist_url") and client.base_url != journal["alist_url"]:
        raise ToolError("ALIST_URL does not match the organize journal's alist_url")

    destination_listing = client.list_dir(journal["destination_path"], refresh=True)
    destination_items = {str(item.get("name", "")): item for item in destination_listing["content"]}
    source_dir_listing_cache = {}
    for record in candidates:
        source_dir = record["source_dir"]
        if source_dir not in source_dir_listing_cache:
            source_dir_listing_cache[source_dir] = client.list_dir(source_dir, refresh=True)
        source_names = {str(item.get("name", "")).casefold()
                        for item in source_dir_listing_cache[source_dir]["content"]}
        if record["name"].casefold() in source_names:
            raise ToolError("Original location is occupied: {}".format(record["source_path"]))
        item = destination_items.get(record["name"])
        if item is None or not item.get("is_dir"):
            raise ToolError("Moved folder changed or disappeared: {}".format(record["target_path"]))

    journal["status"] = "rolling_back"
    atomic_json_write(args.journal, journal)
    failures = []
    for record in candidates:
        try:
            client.move(record["target_dir"], record["source_dir"], [record["name"]])
            record["state"] = "rolled_back"
            record["error"] = None
        except Exception as exc:
            record["state"] = "rollback_failed"
            record["error"] = str(exc)
            failures.append(record["target_path"])
        atomic_json_write(args.journal, journal)
        time.sleep(args.move_delay)
    journal["status"] = "rollback_incomplete" if failures else "rolled_back"
    journal["rolled_back_at"] = utc_now()
    if journal.get("destination_created"):
        journal["rollback_note"] = "Empty destination retained; this Skill never deletes directories."
    atomic_json_write(args.journal, journal)
    try:
        update_state_after_organize(args, journal, reverse=True)
    except Exception as exc:
        eprint("WARNING: Remote organize rollback completed but state update failed: {}".format(exc))
    if failures:
        raise ToolError("Organize rollback incomplete for {} folders; inspect {}".format(
            len(failures), args.journal
        ))
    print("Organize rollback complete: {} folders restored".format(len(candidates)))


def command_login(args):
    if not sys.stdin.isatty():
        raise ToolError("login must be run interactively in the user's terminal")
    if os.environ.get("ALIST_TOKEN") or os.environ.get("ALIST_TOKEN_FILE"):
        raise ToolError("Unset ALIST_TOKEN and ALIST_TOKEN_FILE before creating a new token")
    username = os.environ.get("ALIST_USERNAME", "")
    if not username:
        raise ToolError("Set ALIST_USERNAME for the temporary least-privilege AList user")
    if os.environ.get("ALIST_PASSWORD") is not None:
        raise ToolError("Unset ALIST_PASSWORD; login prompts securely instead")
    destination = Path(args.token_file)
    if destination.exists():
        raise ToolError("Token file already exists; choose another path")
    password = getpass.getpass("AList password: ")
    client = AListClient.from_environment(args.timeout, interactive=False)
    client.password = password
    try:
        client.ensure_token()
    finally:
        password = None
        client.password = None
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(client.token)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            destination.unlink()
        except OSError:
            pass
        raise
    print("Temporary AList token written with mode 0600 to {}".format(destination))
    print("Set ALIST_TOKEN_FILE to this path, then delete it and revoke the user after testing.")


def build_scan_plan(args):
    client = AListClient.from_environment(args.timeout, args.interactive_auth)
    settings = client.settings()
    files, directory_names, directory_meta = walk_alist(
        client, args.path, args.max_files, refresh=args.refresh, delay=args.list_delay
    )
    entries = []
    for item in files:
        name = item["name"]
        extension = Path(name).suffix.lower()
        if extension not in VIDEO_EXTENSIONS:
            continue
        parent_hint = posixpath.basename(item["directory"].rstrip("/"))
        parsed = parse_video_name(name, args.kind, parent_hint=parent_hint)
        new_name = build_name(parsed)
        if not safe_component(Path(new_name).stem):
            parsed["status"] = "review"
            parsed["reason"].append("empty_target_name")
        if len(new_name.encode("utf-8")) > 255:
            parsed["status"] = "review"
            parsed["reason"].append("target_name_exceeds_255_bytes")
        entries.append(
            {
                "old_path": item["full_path"],
                "directory": item["directory"],
                "old_name": name,
                "new_name": new_name,
                "media_type": parsed["media_type"],
                "detected_title": parsed.get("detected_title"),
                "year": parsed.get("year"),
                "season": parsed.get("season"),
                "episode": parsed.get("episode"),
                "size": item.get("size"),
                "modified": item.get("modified"),
                "confidence": parsed["confidence"],
                "status": parsed["status"],
                "reason": parsed["reason"],
            }
        )
    resolver = getattr(args, "resolver", "none")
    tmdb_resolution = None
    if resolver in {"auto", "tmdb"}:
        if TMDBClient.configured():
            tmdb_client = TMDBClient.from_environment(
                args.timeout, getattr(args, "tmdb_rate", 5.0)
            )
            tmdb_resolution = resolve_tmdb_entries(
                tmdb_client, entries,
                language=getattr(args, "tmdb_language", "en-US"),
                max_candidates=getattr(args, "max_candidates", 3),
            )
            eprint("INFO: TMDB BYOK candidate lookup complete; user confirmation is still required.")
        elif resolver == "tmdb":
            raise ToolError("--resolver tmdb requires TMDB_TOKEN_FILE or TMDB_READ_TOKEN")
        else:
            eprint("INFO: No TMDB token configured; using local filename parsing only.")
    add_sidecar_entries(entries, files)
    mark_conflicts(entries, directory_names)
    all_writable = all(meta["write"] for meta in directory_meta.values())
    providers = sorted(
        {provider for meta in directory_meta.values() for provider in meta.get("providers", [])}
    )
    plan = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": uuid.uuid4().hex,
        "created_at": utc_now(),
        "alist_url": client.base_url,
        "alist_version": settings.get("version"),
        "root_path": args.path,
        "writable": all_writable,
        "providers": providers,
        "ready_threshold": args.ready_threshold,
        "metadata_resolver": {
            "kind": "tmdb_byok" if tmdb_resolution is not None else "local_filename",
            "language": getattr(args, "tmdb_language", "en-US"),
            "resolution": tmdb_resolution,
        },
        "summary": summarize(entries),
        "entries": entries,
    }
    return plan


def command_plan(args):
    plan = build_scan_plan(args)
    atomic_json_write(args.output, plan)
    if args.csv:
        write_csv(args.csv, plan["entries"])
    print(json.dumps(plan["summary"], ensure_ascii=False, indent=2))
    print("Plan written to {}".format(args.output))
    if args.csv:
        print("CSV review sheet written to {}".format(args.csv))
    if not plan["writable"]:
        eprint("WARNING: At least one scanned directory is read-only; apply will stop.")


def write_pending_csv(path, entries):
    columns = [
        "state_status", "plan_status", "media_type", "old_path", "new_name",
        "previous_path", "detected_title", "year", "tmdb_id", "size", "modified", "reason",
    ]
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for entry in entries:
            row = dict(entry)
            row["plan_status"] = entry.get("status")
            row["reason"] = ",".join(entry.get("reason") or [])
            writer.writerow(row)


def command_state_init(args):
    state_db = state_db_from_args(args)
    if not state_db:
        raise ToolError("--state-db is required")
    with StateLedger(state_db, create=True) as ledger:
        payload = ledger.summary()
    payload["state_db"] = str(Path(state_db))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def command_state_status(args):
    state_db = state_db_from_args(args)
    if not state_db:
        raise ToolError("--state-db is required")
    with StateLedger(state_db, create=False) as ledger:
        payload = ledger.summary()
    payload["state_db"] = str(Path(state_db))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def import_journal_into_ledger(ledger, journal):
    base_url = journal.get("alist_url")
    if not base_url:
        raise ToolError("Journal is missing alist_url")
    run_id = journal.get("run_id") or "rebuild-" + uuid.uuid4().hex
    imported = 0
    if journal.get("journal_kind") == "organize_move":
        validate_organize_journal(journal)
        for record in journal["entries"]:
            if record.get("state") == "moved":
                imported += ledger.rewrite_prefix(
                    base_url, record["source_path"], record["target_path"], run_id,
                    organization_version=ORGANIZATION_RULE_VERSION,
                )
            elif record.get("state") == "rolled_back":
                imported += ledger.rewrite_prefix(
                    base_url, record["target_path"], record["source_path"], run_id,
                    organization_version=ORGANIZATION_RULE_VERSION,
                )
        return imported

    validate_journal(journal)
    for record in journal["entries"]:
        media_type = record.get("media_type")
        target_name = posixpath.basename(record.get("target_path") or "")
        extension = Path(target_name).suffix.lower()
        if not media_type and extension in SUBTITLE_EXTENSIONS:
            media_type = "subtitle"
        elif not media_type and extension in VIDEO_EXTENSIONS:
            media_type = parse_video_name(target_name, "auto").get("media_type")
        state = record.get("state")
        if media_type == "folder":
            if state == "applied":
                imported += ledger.rewrite_prefix(
                    base_url, record["old_path"], record["target_path"], run_id,
                    folder_version=FOLDER_RULE_VERSION,
                )
            elif state == "rolled_back":
                imported += ledger.rewrite_prefix(
                    base_url, record["target_path"], record["old_path"], run_id,
                    folder_version=FOLDER_RULE_VERSION,
                )
            continue
        entry = {
            "old_path": record["old_path"],
            "media_type": media_type,
            "tmdb_id": record.get("tmdb_id"),
        }
        if entry["tmdb_id"] is None:
            match = TMDB_TAG_RE.search(target_name)
            if match:
                entry["tmdb_id"] = int(match.group("id"))
        if state == "applied":
            ledger.record_processed(
                base_url, entry, record["target_path"], run_id,
                size=record.get("size"), modified=record.get("modified"),
            )
            imported += 1
        elif state == "rolled_back":
            ledger.record_processed(
                base_url, entry, record["old_path"], run_id,
                size=record.get("size"), modified=record.get("modified"),
                status="rolled_back",
            )
            imported += 1
    return imported


def command_state_rebuild(args):
    if not args.journal:
        raise ToolError("Repeat --journal in oldest-to-newest order")
    with StateLedger(args.output_db, create=True, require_new=True) as ledger:
        imported = 0
        for journal_path in args.journal:
            imported += import_journal_into_ledger(ledger, load_json(journal_path))
        payload = ledger.summary()
    payload.update({
        "output_db": str(Path(args.output_db)),
        "journals_imported": len(args.journal),
        "asset_or_path_updates": imported,
    })
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def command_pending_report(args):
    state_db = state_db_from_args(args)
    if not state_db:
        raise ToolError("--state-db is required")
    plan = build_scan_plan(args)
    state_counts = Counter()
    visible = []
    pending_states = {
        "ready", "review", "conflict", "needs_recheck", "changed_since_processed",
        "moved_externally", "rolled_back",
    }
    with StateLedger(state_db, create=False) as ledger:
        for entry in plan["entries"]:
            state_status, previous = ledger.classify(plan["alist_url"], entry)
            entry["state_status"] = state_status
            entry["previous_path"] = previous["current_path"] if previous is not None else None
            entry["recorded_rule_version"] = (
                previous["file_rule_version"] if previous is not None else None
            )
            entry["expected_rule_version"] = file_rule_version(entry.get("media_type"))
            state_counts[state_status] += 1
            if args.include_processed or state_status in pending_states:
                visible.append(entry)
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": "pending_state",
        "created_at": utc_now(),
        "alist_url": plan["alist_url"],
        "root_path": plan["root_path"],
        "state_schema_version": STATE_SCHEMA_VERSION,
        "skill_version": SKILL_RELEASE_VERSION,
        "state_summary": dict(state_counts),
        "pending_count": sum(state_counts[state] for state in pending_states),
        "includes_processed": bool(args.include_processed),
        "entries": visible,
    }
    atomic_json_write(args.output, report)
    if args.csv:
        write_pending_csv(args.csv, visible)
    print(json.dumps({
        "state_summary": report["state_summary"],
        "pending_count": report["pending_count"],
        "reported_entries": len(visible),
    }, ensure_ascii=False, indent=2))
    print("Pending report written to {}".format(args.output))
    if args.csv:
        print("Pending CSV written to {}".format(args.csv))


def live_target_metadata(client, entries):
    by_directory = defaultdict(list)
    for entry in entries:
        if entry.get("media_type") in {"movie", "tv", "subtitle"}:
            by_directory[entry["directory"]].append(entry)
    metadata = {}
    for directory, group in by_directory.items():
        listing = client.list_dir(directory, refresh=True)
        items = {str(item.get("name", "")): item for item in listing["content"]}
        for entry in group:
            item = items.get(entry["new_name"])
            if item is not None:
                metadata[join_path(directory, entry["new_name"])] = item
    return metadata


def update_state_after_apply(args, plan, journal, client):
    state_db = state_db_from_args(args)
    if not state_db:
        return
    by_old_path = {entry["old_path"]: entry for entry in plan["entries"]}
    applied_entries = [by_old_path[record["old_path"]] for record in journal["entries"]
                       if record.get("state") == "applied" and record["old_path"] in by_old_path]
    metadata = live_target_metadata(client, applied_entries)
    with StateLedger(state_db, create=True) as ledger:
        for record in journal["entries"]:
            if record.get("state") != "applied":
                continue
            entry = by_old_path.get(record["old_path"])
            if entry is None:
                continue
            if entry.get("media_type") == "folder":
                ledger.rewrite_prefix(
                    plan["alist_url"], record["old_path"], record["target_path"],
                    journal["run_id"], folder_version=FOLDER_RULE_VERSION,
                )
                continue
            item = metadata.get(record["target_path"], {})
            ledger.record_processed(
                plan["alist_url"], entry, record["target_path"], journal["run_id"],
                size=item.get("size", entry.get("size")),
                modified=item.get("modified", entry.get("modified")),
            )


def update_state_after_rollback(args, journal):
    state_db = state_db_from_args(args)
    if not state_db or not Path(state_db).is_file():
        return
    base_url = journal.get("alist_url")
    if not base_url:
        return
    with StateLedger(state_db, create=False) as ledger:
        for record in journal["entries"]:
            if record.get("state") != "rolled_back":
                continue
            if record.get("media_type") == "folder":
                ledger.rewrite_prefix(
                    base_url, record["target_path"], record["old_path"],
                    journal.get("run_id"), folder_version=FOLDER_RULE_VERSION,
                )
            else:
                ledger.mark_rolled_back(
                    base_url, record["target_path"], record["old_path"],
                    record.get("media_type"), journal.get("run_id"),
                )


def update_state_after_organize(args, journal, reverse=False):
    state_db = state_db_from_args(args)
    if not state_db or not Path(state_db).is_file():
        return
    base_url = journal.get("alist_url")
    if not base_url:
        return
    expected_state = "rolled_back" if reverse else "moved"
    with StateLedger(state_db, create=False) as ledger:
        for record in journal["entries"]:
            if record.get("state") != expected_state:
                continue
            old_prefix = record["target_path"] if reverse else record["source_path"]
            new_prefix = record["source_path"] if reverse else record["target_path"]
            ledger.rewrite_prefix(
                base_url, old_prefix, new_prefix, journal.get("run_id"),
                organization_version=ORGANIZATION_RULE_VERSION,
            )


def command_select(args):
    plan = load_json(args.plan)
    validate_plan(plan)
    requested = list(dict.fromkeys(args.old_path))
    if len(requested) != len(args.old_path):
        raise ToolError("--old-path values must be unique")
    if not 1 <= len(requested) <= 20:
        raise ToolError("Canary selection requires between 1 and 20 video paths")
    if args.expected_videos is not None and args.expected_videos != len(requested):
        raise ToolError("--expected-videos does not match the number of selected paths")
    by_path = {entry["old_path"]: entry for entry in plan["entries"]}
    videos = []
    for old_path in requested:
        entry = by_path.get(old_path)
        if entry is None:
            raise ToolError("Selected path is not present in the plan: {}".format(old_path))
        if entry.get("media_type") not in {"movie", "tv"}:
            raise ToolError("Select video paths only; subtitles are included automatically")
        if entry.get("status") != "ready":
            raise ToolError("Selected video is not ready; approve it first: {}".format(old_path))
        if entry.get("new_name") == entry.get("old_name"):
            raise ToolError("Selected video does not require a rename: {}".format(old_path))
        videos.append(entry)
    selected_video_paths = {entry["old_path"] for entry in videos}
    entries = list(videos)
    paired_sidecars = [
        entry for entry in plan["entries"]
        if entry.get("source_video") in selected_video_paths
    ]
    for sidecar in paired_sidecars:
        if sidecar.get("status") != "ready" or sidecar.get("new_name") == sidecar.get("old_name"):
            raise ToolError(
                "Paired sidecar is not safely executable; resolve it before selection: {}".format(
                    sidecar.get("old_path")
                )
            )
    entries.extend(paired_sidecars)
    output_path = Path(args.output).resolve()
    if output_path == Path(args.plan).resolve():
        raise ToolError("--output must not overwrite the source plan")
    canary = dict(plan)
    canary["plan_id"] = uuid.uuid4().hex
    canary["parent_plan_id"] = plan.get("plan_id")
    canary["created_at"] = utc_now()
    canary["entries"] = entries
    canary["selection"] = {
        "kind": "canary",
        "selected_at": utc_now(),
        "video_count": len(videos),
        "file_count": len(entries),
        "video_old_paths": requested,
    }
    canary["summary"] = summarize(entries)
    validate_plan(canary)
    atomic_json_write(args.output, canary)
    print("Canary plan: {} videos, {} total files including sidecars".format(
        len(videos), len(entries)
    ))
    for entry in videos:
        print("{} -> {}".format(entry["old_path"], entry["new_name"]))
    print("Canary plan written to {}".format(args.output))


def validate_plan(plan):
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise ToolError("Unsupported plan schema_version")
    if not plan.get("root_path") or not isinstance(plan.get("entries"), list):
        raise ToolError("Invalid plan: root_path or entries missing")
    root = plan["root_path"].rstrip("/") or "/"
    for entry in plan["entries"]:
        required = {"old_path", "directory", "old_name", "new_name", "status", "confidence"}
        if not required.issubset(entry):
            raise ToolError("Invalid plan entry: {}".format(entry))
        if parent_path(entry["old_path"]) != entry["directory"]:
            raise ToolError("Plan path boundary mismatch: {}".format(entry["old_path"]))
        if root != "/" and not (
            entry["old_path"] == root or entry["old_path"].startswith(root + "/")
        ):
            raise ToolError("Plan entry escapes root_path: {}".format(entry["old_path"]))
        if "/" in entry["new_name"] or entry["new_name"] in {"", ".", ".."}:
            raise ToolError("Unsafe target filename: {}".format(entry["new_name"]))


def validate_manual_target(old_name, new_name):
    if not new_name or new_name.startswith(".") or "/" in new_name or new_name in {".", ".."}:
        raise ToolError("Unsafe manual target filename: {}".format(new_name))
    if INVALID_COMPONENT_RE.search(new_name):
        raise ToolError("Manual target contains cross-platform unsafe characters")
    if len(new_name.encode("utf-8")) > 255:
        raise ToolError("Manual target exceeds 255 UTF-8 bytes")
    if Path(old_name).suffix.casefold() != Path(new_name).suffix.casefold():
        raise ToolError("Manual approval must preserve the original file extension")
    extension = Path(new_name).suffix
    stem = new_name[: -len(extension)] if extension else new_name
    if CJK_RE.search(stem):
        raise ToolError(
            "Video filenames stay canonical; move the localized title to the folder label: {}"
            .format(new_name)
        )
    for token in stem.split("."):
        if LANGUAGE_TAG_RE.match(token):
            raise ToolError(
                "Manual target keeps an embedded-subtitle/language marker '{}'; "
                "see references/naming.md".format(token)
            )


def validate_tv_target_without_year(new_name):
    extension = Path(new_name).suffix
    stem = new_name[: -len(extension)] if extension else new_name
    episode_match = find_episode(stem)
    if episode_match is None:
        raise ToolError("TV manual target must include an SxxEyy episode marker")
    if find_year_before(stem, episode_match.start()) is not None:
        raise ToolError("TV episode filenames must omit the series first-air year")


def command_approve(args):
    plan = load_json(args.plan)
    validate_plan(plan)
    matches = [entry for entry in plan["entries"] if entry["old_path"] == args.old_path]
    if len(matches) != 1:
        raise ToolError("--old-path must match exactly one plan entry")
    entry = matches[0]
    if entry["media_type"] not in {"movie", "tv"}:
        raise ToolError("Approve the parent video entry, not a subtitle or unsupported file")
    if entry["status"] == "conflict":
        raise ToolError("Resolve the existing conflict before manual approval")
    validate_manual_target(entry["old_name"], args.new_name)
    if entry["media_type"] == "tv":
        validate_tv_target_without_year(args.new_name)
    filename_ids = {int(match.group("id")) for match in TMDB_TAG_RE.finditer(args.new_name)}
    if len(filename_ids) > 1:
        raise ToolError("Manual target contains more than one TMDB ID")
    filename_id = next(iter(filename_ids), None)
    if args.tmdb_id is not None and args.tmdb_id <= 0:
        raise ToolError("--tmdb-id must be a positive integer")
    if args.tmdb_id is not None and filename_id is not None and args.tmdb_id != filename_id:
        raise ToolError("--tmdb-id does not match the {tmdb-ID} filename tag")
    tmdb_id = args.tmdb_id if args.tmdb_id is not None else filename_id
    if entry["media_type"] == "movie" and tmdb_id is not None and filename_id is None:
        raise ToolError("Movie --tmdb-id must also appear in --new-name as {tmdb-ID}")
    old_target_name = entry["new_name"]
    entry["new_name"] = args.new_name
    entry["status"] = "ready"
    entry["confidence"] = 1.0
    entry.setdefault("reason", []).append("manually_verified")
    entry["verification_note"] = args.note or "verified by user"
    if tmdb_id is not None:
        entry["tmdb_id"] = tmdb_id
        entry["tmdb_scope"] = "movie" if entry["media_type"] == "movie" else "tv_series"
        entry["tmdb_id_verified"] = True

    old_video_ext = Path(entry["old_name"]).suffix
    old_video_stem = entry["old_name"][: -len(old_video_ext)] if old_video_ext else entry["old_name"]
    target_video_ext = Path(args.new_name).suffix
    target_video_stem = args.new_name[: -len(target_video_ext)] if target_video_ext else args.new_name
    for sidecar in plan["entries"]:
        if sidecar.get("source_video") != entry["old_path"]:
            continue
        sidecar_ext = Path(sidecar["old_name"]).suffix
        sidecar_stem = sidecar["old_name"][: -len(sidecar_ext)] if sidecar_ext else sidecar["old_name"]
        remainder = sidecar_stem[len(old_video_stem) :] if sidecar_stem.startswith(old_video_stem) else ""
        sidecar["new_name"] = target_video_stem + remainder + sidecar_ext
        sidecar["status"] = "ready"
        sidecar["confidence"] = 1.0
        sidecar.setdefault("reason", []).append("manually_verified_with_video")
        if tmdb_id is not None:
            sidecar["tmdb_id"] = tmdb_id
            sidecar["tmdb_scope"] = entry["tmdb_scope"]
            sidecar["tmdb_id_verified"] = True

    directory_names = defaultdict(set)
    for item in plan["entries"]:
        directory_names[item["directory"]].add(item["old_name"])
    mark_conflicts(plan["entries"], directory_names)
    if entry["status"] == "conflict":
        entry["new_name"] = old_target_name
        raise ToolError("Manual target conflicts with another plan entry")
    plan["summary"] = summarize(plan["entries"])
    plan["reviewed_at"] = utc_now()
    output = args.output or str(Path(args.plan).with_name(Path(args.plan).stem + ".approved.json"))
    atomic_json_write(output, plan)
    print("Approved: {} -> {}".format(entry["old_path"], entry["new_name"]))
    print("Approved plan written to {}".format(output))


def selected_entries(plan, threshold):
    return [
        entry for entry in plan["entries"]
        if entry["status"] == "ready"
        and float(entry.get("confidence") or 0) >= threshold
        and entry["new_name"] != entry["old_name"]
    ]


def validate_live_directories(client, entries):
    by_dir = defaultdict(list)
    for entry in entries:
        by_dir[entry["directory"]].append(entry)
    live_names = {}
    for directory, group in by_dir.items():
        listing = client.list_dir(directory, refresh=True)
        if not listing["write"]:
            raise ToolError("Directory is read-only: {}".format(directory))
        live_items = {item["name"]: item for item in listing["content"]}
        names = set(live_items)
        folded = {name.casefold() for name in names}
        live_names[directory] = names
        planned_old = {entry["old_name"].casefold() for entry in group}
        for entry in group:
            if entry["old_name"] not in names:
                raise ToolError("Source changed or disappeared: {}".format(entry["old_path"]))
            if entry.get("media_type") == "folder" and not live_items[entry["old_name"]].get("is_dir"):
                raise ToolError("Planned folder source is no longer a directory: {}".format(
                    entry["old_path"]
                ))
            target = entry["new_name"].casefold()
            if target in folded and target not in planned_old:
                raise ToolError("Target already exists: {}".format(join_path(directory, entry["new_name"])))
    return live_names


def make_journal(plan, entries, journal_path):
    run_id = uuid.uuid4().hex
    records = []
    for index, entry in enumerate(entries):
        extension = "" if entry.get("media_type") == "folder" else Path(entry["old_name"]).suffix
        temp_name = ".alist-vidhub-tmp-{}-{:06d}{}".format(run_id[:10], index, extension)
        records.append(
            {
                "old_path": entry["old_path"],
                "old_name": entry["old_name"],
                "directory": entry["directory"],
                "temp_name": temp_name,
                "temp_path": join_path(entry["directory"], temp_name),
                "new_name": entry["new_name"],
                "target_path": join_path(entry["directory"], entry["new_name"]),
                "media_type": entry.get("media_type"),
                "size": entry.get("size"),
                "modified": entry.get("modified"),
                "tmdb_id": entry.get("tmdb_id"),
                "state": "pending",
                "error": None,
            }
        )
    journal = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "plan_id": plan.get("plan_id"),
        "alist_url": plan.get("alist_url"),
        "root_path": plan["root_path"],
        "created_at": utc_now(),
        "status": "running",
        "entries": records,
    }
    atomic_json_write(journal_path, journal)
    return journal


def attempt_failure_restore(client, journal, journal_path, delay):
    journal["status"] = "restore_after_failure"
    atomic_json_write(journal_path, journal)
    for record in reversed(journal["entries"]):
        if record["state"] == "applied":
            source = record["target_path"]
        elif record["state"] == "temporary":
            source = record["temp_path"]
        else:
            continue
        try:
            record["restore_source_path"] = source
            client.rename(source, record["old_name"])
            record["state"] = "restored"
            record["error"] = None
            record["restore_source_path"] = None
        except Exception as exc:
            record["state"] = "restore_failed"
            record["error"] = str(exc)
        atomic_json_write(journal_path, journal)
        time.sleep(delay)
    journal["status"] = (
        "restored" if all(r["state"] in {"pending", "restored"} for r in journal["entries"])
        else "manual_recovery_required"
    )
    atomic_json_write(journal_path, journal)


def path_is_within(root, path):
    root = root.rstrip("/") or "/"
    return path == root or (root != "/" and path.startswith(root + "/"))


def validate_journal(journal):
    if journal.get("schema_version") != SCHEMA_VERSION or not journal.get("root_path"):
        raise ToolError("Invalid or unsupported journal")
    root = journal["root_path"].rstrip("/") or "/"
    if not root.startswith("/"):
        raise ToolError("Journal root_path must be absolute")
    entries = journal.get("entries")
    if not isinstance(entries, list):
        raise ToolError("Invalid journal entries")
    required = {
        "old_path", "old_name", "directory", "temp_name", "temp_path",
        "new_name", "target_path", "state",
    }
    for record in entries:
        if not isinstance(record, dict) or not required.issubset(record):
            raise ToolError("Invalid journal entry")
        for key in ("old_name", "temp_name", "new_name"):
            value = record.get(key)
            if not isinstance(value, str) or not value or "/" in value or value in {".", ".."}:
                raise ToolError("Unsafe journal {}: {}".format(key, value))
        directory = record.get("directory")
        if not isinstance(directory, str) or not directory.startswith("/"):
            raise ToolError("Journal directory must be absolute")
        expected = {
            "old_path": join_path(directory, record["old_name"]),
            "temp_path": join_path(directory, record["temp_name"]),
            "target_path": join_path(directory, record["new_name"]),
        }
        for key, expected_path in expected.items():
            if record.get(key) != expected_path:
                raise ToolError("Journal {} does not match directory/name fields".format(key))
        paths = [directory, record["old_path"], record["temp_path"], record["target_path"]]
        restore_source = record.get("restore_source_path")
        if restore_source is not None:
            if restore_source not in {record["temp_path"], record["target_path"]}:
                raise ToolError("Journal restore_source_path is not a known staged path")
            paths.append(restore_source)
        for path in paths:
            if not path_is_within(root, path):
                raise ToolError("Journal entry escapes root_path: {}".format(path))


def command_apply(args):
    plan = load_json(args.plan)
    validate_plan(plan)
    threshold = args.min_confidence if args.min_confidence is not None else float(plan.get("ready_threshold", 0.85))
    entries = selected_entries(plan, threshold)
    video_count = sum(entry.get("media_type") in {"movie", "tv"} for entry in entries)
    folder_count = sum(entry.get("media_type") == "folder" for entry in entries)
    print("Ready to rename {} videos, {} folders, and {} total paths at confidence >= {:.2f}".format(
        video_count, folder_count, len(entries), threshold
    ))
    for entry in entries[:20]:
        print("{} -> {}".format(entry["old_path"], entry["new_name"]))
    if len(entries) > 20:
        print("... and {} more".format(len(entries) - 20))
    if not args.execute:
        print("Dry run only. Re-run with --execute --confirm-root '{}'".format(plan["root_path"]))
        return
    if plan["root_path"] == "/":
        raise ToolError("Refusing to execute against AList root '/'; create a plan for a narrower path")
    if args.confirm_root != plan["root_path"]:
        raise ToolError("--confirm-root must exactly match {}".format(plan["root_path"]))
    confirm_video_count = getattr(args, "confirm_video_count", None)
    if confirm_video_count is not None and confirm_video_count != video_count:
        raise ToolError("--confirm-video-count does not match the executable video count")
    confirm_folder_count = getattr(args, "confirm_folder_count", None)
    if confirm_folder_count is not None and confirm_folder_count != folder_count:
        raise ToolError("--confirm-folder-count does not match the executable folder count")
    if not entries:
        raise ToolError("No ready entries meet the confidence threshold")
    if not plan.get("writable", False):
        raise ToolError("Plan reports a read-only path; create a fresh plan after fixing permissions")
    client = AListClient.from_environment(args.timeout, args.interactive_auth)
    if plan.get("alist_url") and client.base_url != plan["alist_url"]:
        raise ToolError("ALIST_URL does not match the plan's alist_url")
    live_names = validate_live_directories(client, entries)
    journal_path = args.journal or str(Path(args.plan).with_suffix(".journal.json"))
    if Path(journal_path).exists():
        raise ToolError("Journal already exists; choose another --journal path")
    journal = make_journal(plan, entries, journal_path)
    for record in journal["entries"]:
        if record["temp_name"].casefold() in {name.casefold() for name in live_names[record["directory"]]}:
            raise ToolError("Generated temporary name already exists; no changes were made")
    try:
        for record in journal["entries"]:
            client.rename(record["old_path"], record["temp_name"])
            record["state"] = "temporary"
            atomic_json_write(journal_path, journal)
            time.sleep(args.rename_delay)
        for record in journal["entries"]:
            client.rename(record["temp_path"], record["new_name"])
            record["state"] = "applied"
            atomic_json_write(journal_path, journal)
            time.sleep(args.rename_delay)
    except Exception as exc:
        eprint("ERROR: apply failed; attempting automatic restore: {}".format(exc))
        attempt_failure_restore(client, journal, journal_path, args.rename_delay)
        raise ToolError("Apply failed. Inspect journal {} (status={})".format(journal_path, journal["status"]))
    journal["status"] = "complete"
    journal["completed_at"] = utc_now()
    atomic_json_write(journal_path, journal)
    try:
        update_state_after_apply(args, plan, journal, client)
    except Exception as exc:
        eprint("WARNING: Remote rename succeeded but state update failed: {}".format(exc))
    print("Applied {} renames. Journal: {}".format(len(entries), journal_path))


def command_rollback(args):
    journal = load_json(args.journal)
    validate_journal(journal)
    candidates = [
        record for record in reversed(journal.get("entries") or [])
        if record.get("state") in {"applied", "temporary", "restore_failed"}
    ]
    print("Rollback would restore {} paths".format(len(candidates)))
    if not args.execute:
        print("Dry run only. Re-run with --execute --confirm-root '{}'".format(journal["root_path"]))
        return
    if journal["root_path"] == "/":
        raise ToolError("Refusing to roll back against AList root '/'; inspect the journal manually")
    if args.confirm_root != journal["root_path"]:
        raise ToolError("--confirm-root must exactly match {}".format(journal["root_path"]))
    client = AListClient.from_environment(args.timeout, args.interactive_auth)
    if journal.get("alist_url") and client.base_url != journal["alist_url"]:
        raise ToolError("ALIST_URL does not match the journal's alist_url")
    journal["status"] = "rolling_back"
    atomic_json_write(args.journal, journal)
    failures = []
    for record in candidates:
        source = (
            record["target_path"] if record.get("state") == "applied"
            else record.get("restore_source_path") or record["temp_path"]
        )
        listing = client.list_dir(record["directory"], refresh=True)
        names = {item["name"] for item in listing["content"]}
        if record["old_name"] in names:
            record["state"] = "rollback_failed"
            record["error"] = "original name is occupied"
            failures.append(record["old_path"])
            atomic_json_write(args.journal, journal)
            continue
        try:
            client.rename(source, record["old_name"])
            record["state"] = "rolled_back"
            record["error"] = None
        except Exception as exc:
            record["state"] = "rollback_failed"
            record["error"] = str(exc)
            failures.append(record["old_path"])
        atomic_json_write(args.journal, journal)
        time.sleep(args.rename_delay)
    journal["status"] = "rollback_incomplete" if failures else "rolled_back"
    journal["rolled_back_at"] = utc_now()
    atomic_json_write(args.journal, journal)
    try:
        update_state_after_rollback(args, journal)
    except Exception as exc:
        eprint("WARNING: Remote rollback completed but state update failed: {}".format(exc))
    if failures:
        raise ToolError("Rollback incomplete for {} paths; inspect {}".format(len(failures), args.journal))
    print("Rollback complete: {} paths restored".format(len(candidates)))


def build_parser():
    parser = argparse.ArgumentParser(
        description="Create and safely apply Infuse/VidHub-friendly rename plans through the AList API"
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    parser.add_argument(
        "--interactive-auth", action="store_true",
        help="Prompt for ALIST_PASSWORD when ALIST_USERNAME is set (never stores it)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Check version, provider, and write access")
    check.add_argument("--path", required=True, help="Absolute AList path")
    check.set_defaults(func=command_check)

    state_init = subparsers.add_parser(
        "state-init", help="Create or validate the local version-aware processing ledger"
    )
    state_init.add_argument("--state-db", default=DEFAULT_STATE_DB)
    state_init.set_defaults(func=command_state_init)

    state_status = subparsers.add_parser(
        "state-status", help="Show local processing-ledger versions and counts"
    )
    state_status.add_argument("--state-db", default=DEFAULT_STATE_DB)
    state_status.set_defaults(func=command_state_status)

    state_rebuild = subparsers.add_parser(
        "state-rebuild", help="Build a new ledger from exact journals in chronological order"
    )
    state_rebuild.add_argument(
        "--journal", action="append", required=True,
        help="Exact journal path; repeat in oldest-to-newest order",
    )
    state_rebuild.add_argument("--output-db", required=True, help="New database path")
    state_rebuild.set_defaults(func=command_state_rebuild)

    login = subparsers.add_parser(
        "login", help="Interactively create a mode-0600 temporary token file"
    )
    login.add_argument("--token-file", required=True, help="New local file for the temporary JWT")
    login.set_defaults(func=command_login)

    tmdb_setup = subparsers.add_parser(
        "tmdb-setup", help="Interactively verify and store a user-owned TMDB Read Access Token"
    )
    tmdb_setup.add_argument("--token-file", required=True, help="New mode-0600 local token file")
    tmdb_setup.add_argument(
        "--accept-terms", action="store_true",
        help="Confirm that the user reviewed and accepts the current TMDB API terms",
    )
    tmdb_setup.add_argument("--tmdb-rate", type=float, default=5.0)
    tmdb_setup.set_defaults(func=command_tmdb_setup)

    tmdb_check = subparsers.add_parser(
        "tmdb-check", help="Validate the configured user-owned TMDB credential"
    )
    tmdb_check.add_argument("--tmdb-rate", type=float, default=5.0)
    tmdb_check.set_defaults(func=command_tmdb_check)

    plan = subparsers.add_parser("plan", help="Scan recursively and write a dry-run plan")
    plan.add_argument("--path", required=True, help="Absolute AList path to scan")
    plan.add_argument("--output", required=True, help="JSON plan output path")
    plan.add_argument("--csv", help="Optional UTF-8 CSV review sheet")
    plan.add_argument("--kind", choices=["auto", "movie", "tv"], default="auto")
    plan.add_argument("--max-files", type=int, default=100000)
    plan.add_argument("--ready-threshold", type=float, default=0.85)
    plan.add_argument("--refresh", action="store_true", help="Refresh AList storage caches while listing")
    plan.add_argument("--list-delay", type=float, default=0.05, help="Delay between directory listings")
    plan.add_argument(
        "--resolver", choices=["auto", "tmdb", "none"], default="auto",
        help="auto uses TMDB when a user-owned token is configured; otherwise local parsing",
    )
    plan.add_argument("--tmdb-language", default="en-US")
    plan.add_argument("--tmdb-rate", type=float, default=5.0)
    plan.add_argument("--max-candidates", type=int, default=3)
    plan.set_defaults(func=command_plan)

    pending = subparsers.add_parser(
        "pending-report", help="Scan and report only new, changed, stale-rule, or conflicted media"
    )
    pending.add_argument("--path", required=True, help="Absolute AList path to scan")
    pending.add_argument("--state-db", default=DEFAULT_STATE_DB)
    pending.add_argument("--output", required=True, help="JSON pending report path")
    pending.add_argument("--csv", help="Optional UTF-8 pending-only CSV")
    pending.add_argument("--include-processed", action="store_true")
    pending.add_argument("--kind", choices=["auto", "movie", "tv"], default="auto")
    pending.add_argument("--max-files", type=int, default=100000)
    pending.add_argument("--ready-threshold", type=float, default=0.85)
    pending.add_argument("--refresh", action="store_true")
    pending.add_argument("--list-delay", type=float, default=0.05)
    pending.add_argument(
        "--resolver", choices=["auto", "tmdb", "none"], default="none",
        help="none is fastest; TMDB is optional and still never auto-approves candidates",
    )
    pending.add_argument("--tmdb-language", default="en-US")
    pending.add_argument("--tmdb-rate", type=float, default=5.0)
    pending.add_argument("--max-candidates", type=int, default=3)
    pending.set_defaults(func=command_pending_report)

    folder_plan = subparsers.add_parser(
        "folder-plan", help="Create a read-only plan for 1-20 exact direct-child folder renames"
    )
    folder_plan.add_argument("--path", required=True, help="Narrow non-root AList parent path")
    folder_plan.add_argument(
        "--mapping-file", required=True,
        help="Local JSON list of exact old_name/new_name folder mappings",
    )
    folder_plan.add_argument("--output", required=True, help="New local folder plan path")
    folder_plan.set_defaults(func=command_folder_plan)

    organize_plan = subparsers.add_parser(
        "organize-plan", help="Create a read-only plan to move 1-20 folders into Movies/TV Shows"
    )
    organize_plan.add_argument("--path", required=True, help="Narrow non-root AList parent path")
    organize_plan.add_argument("--destination", required=True, help="Exact direct-child destination")
    organize_plan.add_argument(
        "--folder", action="append", required=True,
        help=(
            "Exact source folder under --path; repeat once per folder. "
            "A bare name is a direct child of --path; a 'a/b/c' relative "
            "path selects a folder nested under --path at any depth "
            "(moved as a single unit, landing as a direct child of "
            "--destination)."
        ),
    )
    organize_plan.add_argument("--output", required=True, help="New local organize plan path")
    organize_plan.set_defaults(func=command_organize_plan)

    tmdb_resolve = subparsers.add_parser(
        "tmdb-resolve", help="Add read-only TMDB candidates to an existing local plan"
    )
    tmdb_resolve.add_argument("--plan", required=True)
    tmdb_resolve.add_argument("--output", required=True)
    tmdb_resolve.add_argument("--language", default="en-US")
    tmdb_resolve.add_argument("--tmdb-rate", type=float, default=5.0)
    tmdb_resolve.add_argument("--max-candidates", type=int, default=3)
    tmdb_resolve.set_defaults(func=command_tmdb_resolve)

    select = subparsers.add_parser(
        "select", help="Create a canary plan containing 1-20 exact videos and paired sidecars"
    )
    select.add_argument("--plan", required=True)
    select.add_argument(
        "--old-path", action="append", required=True,
        help="Exact ready video old_path; repeat once per selected video",
    )
    select.add_argument("--expected-videos", type=int)
    select.add_argument("--output", required=True)
    select.set_defaults(func=command_select)

    approve = subparsers.add_parser(
        "approve", help="Approve one manually verified video into a new local plan"
    )
    approve.add_argument("--plan", required=True)
    approve.add_argument("--old-path", required=True, help="Exact old_path from the plan")
    approve.add_argument("--new-name", required=True, help="Verified target filename with extension")
    approve.add_argument(
        "--tmdb-id", type=int,
        help="Manually verified TMDB movie or series ID; never looked up automatically",
    )
    approve.add_argument("--note", help="Non-secret verification note or source")
    approve.add_argument("--output", help="Defaults to <plan>.approved.json")
    approve.set_defaults(func=command_approve)

    apply_cmd = subparsers.add_parser("apply", help="Preview or execute ready entries in a plan")
    apply_cmd.add_argument("--plan", required=True)
    apply_cmd.add_argument("--journal", help="Rollback journal path; must not already exist")
    apply_cmd.add_argument("--min-confidence", type=float)
    apply_cmd.add_argument("--execute", action="store_true")
    apply_cmd.add_argument("--confirm-root", help="Must exactly match plan root when executing")
    apply_cmd.add_argument(
        "--confirm-video-count", type=int,
        help="Optional exact executable video count confirmation for canary runs",
    )
    apply_cmd.add_argument(
        "--confirm-folder-count", type=int,
        help="Optional exact executable folder count confirmation for folder canary runs",
    )
    apply_cmd.add_argument("--rename-delay", type=float, default=0.6)
    apply_cmd.add_argument("--state-db", default=DEFAULT_STATE_DB)
    apply_cmd.set_defaults(func=command_apply)

    organize_apply = subparsers.add_parser(
        "organize-apply", help="Preview or execute an exact folder organization plan"
    )
    organize_apply.add_argument("--plan", required=True)
    organize_apply.add_argument("--journal", help="Rollback journal path; must not already exist")
    organize_apply.add_argument("--execute", action="store_true")
    organize_apply.add_argument("--confirm-root", help="Must exactly match plan root when executing")
    organize_apply.add_argument("--confirm-folder-count", type=int)
    organize_apply.add_argument("--move-delay", type=float, default=0.6)
    organize_apply.add_argument("--state-db", default=DEFAULT_STATE_DB)
    organize_apply.set_defaults(func=command_organize_apply)

    rollback = subparsers.add_parser("rollback", help="Preview or execute rollback from a journal")
    rollback.add_argument("--journal", required=True)
    rollback.add_argument("--execute", action="store_true")
    rollback.add_argument("--confirm-root", help="Must exactly match journal root when executing")
    rollback.add_argument("--rename-delay", type=float, default=0.6)
    rollback.add_argument("--state-db", default=DEFAULT_STATE_DB)
    rollback.set_defaults(func=command_rollback)

    organize_rollback = subparsers.add_parser(
        "organize-rollback", help="Preview or execute reverse moves from an organize journal"
    )
    organize_rollback.add_argument("--journal", required=True)
    organize_rollback.add_argument("--execute", action="store_true")
    organize_rollback.add_argument("--confirm-root", help="Must exactly match journal root")
    organize_rollback.add_argument("--move-delay", type=float, default=0.6)
    organize_rollback.add_argument("--state-db", default=DEFAULT_STATE_DB)
    organize_rollback.set_defaults(func=command_organize_rollback)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except ToolError as exc:
        eprint("ERROR:", exc)
        return 2
    except KeyboardInterrupt:
        eprint("Interrupted")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
