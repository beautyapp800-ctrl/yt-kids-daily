"""The state that has to survive a disposable runner: which video, which cards, what is done.

Same shape as yt-factory's: one SQLite file, committed back to git after every run, because a
GitHub runner is thrown away and output/ is not in git. What survives here is the cheap part -
the plan - while the expensive parts (downloaded clips, drawn pictures, narration) go in the
Actions cache keyed by video id.

A card is the unit, not a scene: one subject, one fact, one clip or one picture, one sound.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "kids.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    theme TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    title TEXT,
    seo_title TEXT,
    description TEXT,
    tags TEXT,
    duration_s REAL,
    video_path TEXT,
    thumbnail_path TEXT,
    youtube_id TEXT,
    published_at TEXT,
    error TEXT,
    attempts INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id),
    idx INTEGER NOT NULL,
    subject TEXT NOT NULL,
    fact TEXT,
    clip_id TEXT,
    clip_url TEXT,
    clip_licence TEXT,
    image_path TEXT,
    video_source TEXT,
    sound_id TEXT,
    sound_licence TEXT,
    sound_url TEXT,
    sound_attribution TEXT,
    audio_path TEXT,
    duration_s REAL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER,
    stage TEXT,
    level TEXT,
    message TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS used_subjects (
    subject TEXT NOT NULL,
    video_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""

_VIDEO_FIELDS = {"theme", "status", "title", "seo_title", "description", "tags", "duration_s",
                 "video_path", "thumbnail_path", "youtube_id", "published_at", "error",
                 "attempts", "cover_subjects", "short_youtube_id", "channel", "theme_id",
                 "title_query"}
_CARD_FIELDS = {"fact", "clip_id", "clip_url", "clip_licence", "image_path", "video_source",
                "sound_id", "sound_licence", "sound_url", "sound_attribution", "audio_path", "duration_s",
                "game_clip_id", "game_clip_url"}

# Columns added after a database already existed. CREATE TABLE IF NOT EXISTS does not add a
# column to a table that is already there, and this database is committed to git and outlives
# every schema change, so new columns arrive here. Caught on the first one: sound_url was
# added to the schema and the existing file carried on without it until an INSERT failed.
_MIGRATIONS = [("cards", "sound_url", "TEXT"),
               ("videos", "cover_subjects", "TEXT"),
               ("cards", "game_clip_id", "TEXT"),
               ("cards", "game_clip_url", "TEXT"),
               ("videos", "short_youtube_id", "TEXT"),
               ("videos", "channel", "TEXT"),
               ("videos", "theme_id", "TEXT"),
               ("videos", "title_query", "TEXT")]

# The channel this process works for: config.youtube_channel_id, set by run.py and the scripts
# once the config is read. The project moved from Moo Toot to another channel on 14 November
# 2026 and the database kept every Moo Toot video, so everything that judges "the channel" -
# the queue, the next slot, what may not be repeated, which video to carry on with - looks only
# at this channel's videos. None (tests, old callers) means every video.
CHANNEL = None
LEGACY_CHANNEL = "moo-toot"       # what the videos made before the move are marked with


def _scope(channel, alias=""):
    """(" AND <alias>channel = ?", [channel]) for the current channel, or ("", [])."""
    channel = channel if channel is not None else CHANNEL
    if not channel:
        return "", []
    return f" AND {alias}channel = ?", [channel]

MAX_ATTEMPTS = 3


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn):
    """Add columns an older database predates. Safe to run on every start."""
    for table, column, decl in _MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            if (table, column) == ("videos", "channel"):
                # Everything already in the database was made for Moo Toot.
                conn.execute("UPDATE videos SET channel = ?", (LEGACY_CHANNEL,))


def create_video(theme, channel=None):
    with _connect() as conn:
        return conn.execute("INSERT INTO videos (created_at, theme, status, channel) "
                            "VALUES (?, ?, 'pending', ?)",
                            (_now(), theme, channel if channel is not None else CHANNEL)).lastrowid


def get_video(video_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return dict(row) if row else None


def update_video(video_id, **fields):
    bad = set(fields) - _VIDEO_FIELDS
    if bad:
        raise ValueError(f"not columns of videos: {sorted(bad)}")
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as conn:
        conn.execute(f"UPDATE videos SET {sets} WHERE id = ?",
                     (*fields.values(), video_id))


def add_card(video_id, idx, subject, **fields):
    with _connect() as conn:
        card_id = conn.execute(
            "INSERT INTO cards (video_id, idx, subject) VALUES (?, ?, ?)",
            (video_id, idx, subject)).lastrowid
    if fields:
        update_card(card_id, **fields)
    return card_id


def update_card(card_id, **fields):
    bad = set(fields) - _CARD_FIELDS
    if bad:
        raise ValueError(f"not columns of cards: {sorted(bad)}")
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as conn:
        conn.execute(f"UPDATE cards SET {sets} WHERE id = ?", (*fields.values(), card_id))


def get_cards(video_id):
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM cards WHERE video_id = ? ORDER BY idx", (video_id,))]


def log_event(video_id, stage, level, message):
    with _connect() as conn:
        conn.execute("INSERT INTO events (video_id, stage, level, message, created_at) "
                     "VALUES (?, ?, ?, ?, ?)", (video_id, stage, level, message, _now()))


def finished_stages(video_id):
    """Stages whose latest event says they finished, so a rerun resumes rather than repeats."""
    done = {}
    with _connect() as conn:
        for row in conn.execute("SELECT stage, message FROM events WHERE video_id = ? "
                                "AND level = 'info' ORDER BY id", (video_id,)):
            if row["message"] in ("stage started", "stage finished"):
                done[row["stage"]] = row["message"] == "stage finished"
    return {stage for stage, ok in done.items() if ok}


def oldest_unfinished(max_attempts=MAX_ATTEMPTS, max_age_days=7, channel=None):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    where, args = _scope(channel)
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM videos WHERE status NOT IN ('published', 'ready') "
            "AND COALESCE(attempts, 0) < ? AND created_at >= ?" + where +
            " ORDER BY created_at, id LIMIT 1",
            (max_attempts, cutoff, *args)).fetchone()
        return dict(row) if row else None


def subjects_used_recently(videos_back=6):
    """Subjects from the last few videos, so a new one does not repeat them straight away."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT subject FROM used_subjects WHERE video_id IN "
            "(SELECT id FROM videos ORDER BY id DESC LIMIT ?)", (videos_back,)).fetchall()
    return {r["subject"] for r in rows}


def recent_videos(limit=12, channel=None):
    """The last few videos, newest first - what they were about, what they were called, and
    which pictures were on their covers. One query, so the planner, the titles and the cover
    all judge variety from the same list."""
    import json as _json
    with _connect() as conn:
        # Only videos that were planned. A day with no theme ready still creates a row and fails
        # it; counting that row as "a video" would make a theme look a day older than it is.
        where, args = _scope(channel)
        rows = conn.execute(
            "SELECT id, theme, seo_title, cover_subjects FROM videos "
            "WHERE id IN (SELECT DISTINCT video_id FROM cards)" + where +
            " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
    out = []
    for r in rows:
        try:
            cover = _json.loads(r["cover_subjects"]) if r["cover_subjects"] else []
        except ValueError:
            cover = []
        out.append({"id": r["id"], "theme": r["theme"], "seo_title": r["seo_title"],
                    "cover_subjects": cover})
    return out


def subjects_used_in_last(videos_back):
    """{subject: how many videos ago it was used}, 1 being the video just made.

    A set of "recently used" cannot say how recently, and the rule is a distance: a subject
    may come back after five videos. So the distance is what is returned.
    """
    with _connect() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM videos WHERE id IN (SELECT DISTINCT video_id FROM used_subjects) "
            "ORDER BY id DESC LIMIT ?", (videos_back,))]
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT subject, video_id FROM used_subjects WHERE video_id IN ({marks})",
            ids).fetchall()
    place = {vid: n + 1 for n, vid in enumerate(ids)}
    out = {}
    for r in rows:
        distance = place.get(r["video_id"])
        if distance and (r["subject"] not in out or distance < out[r["subject"]]):
            out[r["subject"]] = distance
    return out


def remember_subjects(video_id, subjects):
    with _connect() as conn:
        conn.executemany("INSERT INTO used_subjects (subject, video_id, created_at) "
                         "VALUES (?, ?, ?)", [(s, video_id, _now()) for s in subjects])


def last_scheduled_publish(channel=None):
    """The latest publishAt already handed to YouTube, as an aware datetime, or None.

    The queue decides the next slot, not the clock - the same lesson yt-factory learned when
    every scheduled run started hours late and "now plus three days" started skipping days.
    """
    latest = None
    where, args = _scope(channel)
    with _connect() as conn:
        rows = conn.execute("SELECT published_at FROM videos WHERE published_at IS NOT NULL "
                            "AND published_at != '' AND youtube_id IS NOT NULL "
                            "AND youtube_id != ''" + where, args).fetchall()
    for row in rows:
        try:
            when = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if latest is None or when > latest:
            latest = when
    return latest


def scheduled_after(moment, channel=None):
    rows = []
    where, args = _scope(channel)
    with _connect() as conn:
        for row in conn.execute("SELECT id, seo_title, title, youtube_id, published_at "
                                "FROM videos WHERE published_at IS NOT NULL "
                                "AND published_at != '' AND youtube_id IS NOT NULL "
                                "AND youtube_id != ''" + where, args):
            try:
                when = datetime.fromisoformat(str(row["published_at"]).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when > moment:
                rows.append({**dict(row), "when": when})
    return sorted(rows, key=lambda r: r["when"])


def channel_videos(channel=None):
    """Every video of the channel that got as far as a plan, oldest first: id, theme_id,
    titles, and the set of subjects on its cards. What the no-repeat rules are judged against.

    A video counts once it has cards, not once it is public: one that is planned or queued is
    already a promise of those subjects, and the next plan must not repeat it.
    """
    where, args = _scope(channel, "v.")
    with _connect() as conn:
        videos = [dict(r) for r in conn.execute(
            "SELECT v.id, v.theme, v.theme_id, v.seo_title, v.title_query, v.youtube_id, "
            "v.published_at, v.status FROM videos v "
            "WHERE v.id IN (SELECT DISTINCT video_id FROM cards)" + where +
            " ORDER BY v.id", args)]
        for v in videos:
            v["subjects"] = {r["subject"] for r in conn.execute(
                "SELECT subject FROM cards WHERE video_id = ?", (v["id"],))}
    return videos


def clear_cards(video_id):
    """Forget a plan that did not stand, so the next attempt starts clean."""
    with _connect() as conn:
        conn.execute("DELETE FROM cards WHERE video_id = ?", (video_id,))
        conn.execute("DELETE FROM used_subjects WHERE video_id = ?", (video_id,))


def use_configured_channel():
    """Set CHANNEL from config.youtube_channel_id, for the scripts that run on their own."""
    global CHANNEL
    from core.config import load_config
    CHANNEL = load_config().get("youtube_channel_id")
    return CHANNEL
