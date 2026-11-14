"""Offline tests for the move to the new channel (14 November 2026). Run: python tests/test_new_channel.py

What the owner asked for, each held by a check:
  - nothing is uploaded unless the token answers for config.youtube_channel_id;
  - Sunday, Tuesday and Thursday at 16:00 Kyiv, and "Europe/Kiev" no longer breaks it;
  - a theme is used once ever; no video shares more than 30% of its subjects with another,
    checked at the plan and again before upload; the Moo Toot videos are not the new
    channel's history;
  - titles come from real YouTube searches and are never reused;
  - the daily cron only builds when the queue is short.
"""
import json
import random
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import core.logger
core.logger.LOG_DIR = Path(tempfile.mkdtemp(prefix="yt-kids-test-"))

from core import db, suggest, youtube
from pipeline import plan, seo, upload

NEW = "UCX71CVp9h0wn762YHzdo0QQ"
failures = []


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        failures.append(msg)


def fresh(tmp, name, channel=NEW):
    db.DB_PATH = tmp / f"{name}.db"
    db.CHANNEL = channel
    db.init_db()


def add_video(subjects, theme_id=None, channel=NEW, youtube_id=None, published_at=None,
              status="published", title=None, query=None):
    vid = db.create_video("t", channel=channel)
    for i, s in enumerate(subjects):
        db.add_card(vid, i, s)
    fields = {"status": status}
    if theme_id:
        fields["theme_id"] = theme_id
    if youtube_id:
        fields["youtube_id"] = youtube_id
    if published_at:
        fields["published_at"] = published_at
    if title:
        fields["seo_title"] = title
    if query:
        fields["title_query"] = query
    db.update_video(vid, **fields)
    return vid


# --- the schedule --------------------------------------------------------------------------

def test_sunday_tuesday_thursday_at_four_in_kyiv():
    print("test_sunday_tuesday_thursday_at_four_in_kyiv")
    cfg = {"timezone": "Europe/Kyiv", "publish_time": "16:00", "publish_days_ahead": 3,
           "publish_weekdays": ["Sun", "Tue", "Thu"]}
    saturday = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
    first = upload.publish_at(cfg, saturday)
    check(first == "2026-11-17T14:00:00Z",
          f"three days from Saturday 14 Nov is Tuesday 17 Nov, 16:00 Kyiv = 14:00Z ({first})")
    after_tue = upload.publish_at(cfg, saturday, last_scheduled="2026-11-17T14:00:00Z")
    check(after_tue == "2026-11-19T14:00:00Z", f"after Tuesday comes Thursday ({after_tue})")
    after_thu = upload.publish_at(cfg, saturday, last_scheduled="2026-11-19T14:00:00Z")
    check(after_thu == "2026-11-22T14:00:00Z", f"after Thursday comes Sunday ({after_thu})")
    after_sun = upload.publish_at(cfg, saturday, last_scheduled="2026-11-22T14:00:00Z")
    check(after_sun == "2026-11-24T14:00:00Z", f"after Sunday comes Tuesday ({after_sun})")
    evening = datetime(2026, 11, 14, 18, 5, tzinfo=timezone.utc)      # Saturday 20:05 Kyiv
    backfill = upload.publish_at({**cfg, "backfill": True}, evening)
    check(backfill == "2026-11-15T14:00:00Z",
          f"a backfill with an empty queue takes Sunday 15 Nov 16:00 Kyiv ({backfill})")
    late = upload.publish_at({**cfg, "backfill": True},
                             datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc))
    check(late == "2026-11-17T14:00:00Z",
          f"run on Sunday itself, the first slot is the next one, Tuesday ({late})")
    days = set()
    last = None
    for _ in range(12):
        last = upload.publish_at(cfg, saturday, last_scheduled=last)
        days.add(datetime.fromisoformat(last.replace("Z", "+00:00")).astimezone(
            upload.zone("Europe/Kyiv")).strftime("%a %H:%M"))
    check(days == {"Sun 16:00", "Tue 16:00", "Thu 16:00"},
          f"twelve slots in a row land only on Sun/Tue/Thu 16:00 ({sorted(days)})")
    summer = upload.publish_at({**cfg, "timezone": "Europe/Kiev"},
                               datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc))
    check(summer.endswith("T13:00:00Z"),
          f"the old name 'Europe/Kiev' still resolves, and summer is UTC+3 ({summer})")


# --- the themes and the 30% rule -------------------------------------------------------------

def test_the_real_catalogue_never_repeats_a_theme_or_more_than_30_percent():
    print("test_the_real_catalogue_never_repeats_a_theme_or_more_than_30_percent")
    from pipeline import catalogue
    clips = catalogue.load()
    facts = json.loads((ROOT / "assets" / "facts.json").read_text(encoding="utf-8"))
    themes = plan.load_themes()
    ids = [t["id"] for t in themes]
    check(len(ids) == len(set(ids)), f"{len(ids)} themes, every id different")
    ready = plan.ready_subjects(clips, facts)
    videos, made = [], []
    for n in range(40):
        try:
            theme, subjects = plan.choose_from_catalogue(themes, ready, videos, 15, 0.30,
                                                         random.Random(n))
        except plan.NoThemeReady as e:
            stop = str(e)
            break
        videos.append({"id": n + 1, "theme_id": theme["id"], "subjects": set(subjects)})
        made.append(theme["id"])
    check(len(made) >= 7, f"the catalogue as it is makes {len(made)} videos: {made}")
    check(len(made) == len(set(made)), "no theme twice")
    worst = max((len(a["subjects"] & b["subjects"]) for i, a in enumerate(videos)
                 for b in videos[i + 1:]), default=0)
    check(worst <= 4, f"no two videos share more than 4 of 15 subjects (worst {worst})")
    check("a repeat is not an option" in stop,
          "when nothing more can be made, it stops and says why instead of repeating")


def test_a_plan_or_upload_that_repeats_the_channel_is_refused(tmp):
    print("test_a_plan_or_upload_that_repeats_the_channel_is_refused")
    fresh(tmp, "repeat")
    a = [f"s{i}" for i in range(15)]
    add_video(a, theme_id="farm")
    b = add_video(a[:5] + [f"t{i}" for i in range(10)], theme_id="other", status="ready")
    problems = plan.repeat_problems(b, 0.30)
    check(any("5 of 15" in p for p in problems), f"5 shared of 15 is over 30% ({problems})")
    c = add_video(a[:4] + [f"u{i}" for i in range(11)], theme_id="third", status="ready")
    check(not plan.repeat_problems(c, 0.30), "4 shared of 15 is allowed")
    d = add_video([f"v{i}" for i in range(15)], theme_id="farm", status="ready")
    check(any("theme 'farm'" in p for p in plan.repeat_problems(d, 0.30)),
          "the same theme a second time is refused even with new subjects")
    try:
        upload.run(b, {"youtube_channel_id": NEW}, service=None)
        refused = None
    except upload.UploadError as e:
        refused = str(e)
    check(refused is not None and "repeats the channel" in refused,
          f"the upload stage refuses it before anything is sent ({refused})")


def test_moo_toot_is_not_the_new_channel_s_history(tmp):
    print("test_moo_toot_is_not_the_new_channel_s_history")
    db.DB_PATH = tmp / "legacy.db"
    db.CHANNEL = None
    # An old database, as committed before the move: no channel column at all.
    with closing(sqlite3.connect(db.DB_PATH)) as conn:
        conn.executescript(db.SCHEMA)
        conn.execute("INSERT INTO videos (created_at, theme, status, youtube_id, published_at, "
                     "attempts) VALUES (?, 'farm animals', 'failed', NULL, NULL, 1)",
                     (datetime.now(timezone.utc).isoformat(),))
        conn.execute("INSERT INTO videos (created_at, theme, status, youtube_id, published_at) "
                     "VALUES (?, 'birds', 'published', 'old1', ?)",
                     (datetime.now(timezone.utc).isoformat(),
                      (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()))
        conn.commit()
    db.init_db()
    with closing(sqlite3.connect(db.DB_PATH)) as conn:
        marks = {r[0] for r in conn.execute("SELECT channel FROM videos")}
    check(marks == {db.LEGACY_CHANNEL}, f"every video already there is marked Moo Toot ({marks})")
    db.CHANNEL = NEW
    check(db.oldest_unfinished() is None, "an unfinished Moo Toot video is not carried on with")
    check(db.scheduled_after(datetime.now(timezone.utc)) == [],
          "a Moo Toot video still in its queue is not the new channel's queue")
    check(db.last_scheduled_publish() is None, "and does not decide the next slot")
    new = db.create_video("pending")
    check(db.get_video(new)["channel"] == NEW, "a new video belongs to the new channel")


# --- the token ---------------------------------------------------------------------------------

class _Service:
    def __init__(self, items):
        self.items = items

    def channels(self):
        return self

    def list(self, **kw):
        self.asked = kw
        return self

    def execute(self):
        return {"items": self.items}


class _Creds:
    def __init__(self, scopes):
        self.scopes = scopes


def test_the_token_must_answer_for_the_new_channel():
    print("test_the_token_must_answer_for_the_new_channel")
    both = _Creds(youtube.SCOPES)
    right = _Service([{"id": NEW, "snippet": {"title": "Yoga For Health",
                                              "customUrl": "@yogaforhealth-z9e"}}])
    check(youtube.verify_channel(right, NEW, both)[0] == NEW, "the right channel passes")
    wrong = _Service([{"id": "UCmootoot0000000000000", "snippet": {"title": "Moo Toot"}}])
    for name, service, creds in (("another channel", wrong, both),
                                 ("the old upload-only token", right,
                                  _Creds([youtube.UPLOAD_SCOPE])),
                                 ("no channel id in config", right, both)):
        try:
            youtube.verify_channel(service, None if "config" in name else NEW, creds)
            stopped = False
        except youtube.AuthError:
            stopped = True
        check(stopped, f"{name}: refused")


# --- titles --------------------------------------------------------------------------------------

def test_titles_come_from_real_searches_and_are_never_reused():
    print("test_titles_come_from_real_searches_and_are_never_reused")
    for q, ok in (("farm animals for toddlers", True), ("farm animals for dogs", False),
                  ("farm animals for toddlers songs", False), ("rc boats for kids", False),
                  ("farm animals", False), ("vegetables for kids lunch", False),
                  ("arctic animals for kids", False)):
        check(suggest.usable(q, ["farm", "boat", "vegetable"]) == ok, f"{q!r}: {ok}")

    class _Response:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.data).encode()

    def opener(url, timeout=None):
        return _Response(["x", ["farm animals for toddlers", "farm animals for kids",
                                "farm animals for dogs"]])
    theme = plan.theme_by_id("farm-animal-sounds")
    title, query = seo.catalogue_title(theme, 15, True, 1, [], [], opener)
    check(query == "farm animals for toddlers" and title.startswith("Farm Animals for Toddlers |"),
          f"the search leads the title ({title})")
    title2, query2 = seo.catalogue_title(theme, 15, True, 1, [title], [query], opener)
    check(query2 != query and title2 != title, f"a used search is not used again ({title2})")
    check(len(title2) <= 100, "and it fits YouTube's 100 characters")


# --- when the daily cron builds ----------------------------------------------------------------

def test_the_cron_builds_only_when_the_queue_is_short(tmp):
    print("test_the_cron_builds_only_when_the_queue_is_short")
    import ci_should_run
    fresh(tmp, "queue")
    now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    run, why = ci_should_run.decide(now, queue_target=2)
    check(run, f"an empty queue builds ({why})")
    add_video(["a"], youtube_id="y1", published_at="2026-11-17T14:00:00Z")
    add_video(["b"], youtube_id="y2", published_at="2026-11-19T14:00:00Z")
    run, why = ci_should_run.decide(now, queue_target=2)
    check(not run and "already scheduled" in why, f"two in the queue wait ({why})")
    add_video(["c"], youtube_id="old", published_at="2026-11-21T14:00:00Z",
              channel=db.LEGACY_CHANNEL)
    later = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    run, why = ci_should_run.decide(later, queue_target=2)
    check(run, f"one left, and a Moo Toot video does not count ({why})")


def test_grow_works_for_the_next_themes_that_lack_something():
    print("test_grow_works_for_the_next_themes_that_lack_something")
    import grow
    themes = [{"id": "full", "category": "c", "subjects": ["a", "b"]},
              {"id": "used", "category": "c", "subjects": ["x"]},
              {"id": "short", "category": "insects", "subjects": ["a", "new1", "tried"]}]
    clips = {"tried": {"clips": [], "search_term": "tried"}}
    out = grow.upcoming_missing(themes, [{"theme_id": "used"}], {"a", "b"}, clips, {}, ahead=1)
    check(out == [("insects", "new1")],
          f"a complete theme is skipped, a failed subject not retried ({out})")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_sunday_tuesday_thursday_at_four_in_kyiv()
        test_the_real_catalogue_never_repeats_a_theme_or_more_than_30_percent()
        test_a_plan_or_upload_that_repeats_the_channel_is_refused(tmp)
        test_moo_toot_is_not_the_new_channel_s_history(tmp)
        test_the_token_must_answer_for_the_new_channel()
        test_titles_come_from_real_searches_and_are_never_reused()
        test_the_cron_builds_only_when_the_queue_is_short(tmp)
        test_grow_works_for_the_next_themes_that_lack_something()
    db.CHANNEL = None
    if failures:
        print(f"\n{len(failures)} NEW CHANNEL TEST(S) FAILED")
        sys.exit(1)
    print("\nALL NEW CHANNEL TESTS PASSED")
