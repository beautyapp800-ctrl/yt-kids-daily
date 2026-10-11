"""Offline tests for the plan stage. Run: python tests/test_plan.py

Fake catalogues, a temporary database, no network and no model. What is tested is what a viewer
would notice: a video of lions that is called "Fruit And Vegetables", the same picture twice,
and a plan that comes out short because one theme ran out.
"""
import json
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.logger
core.logger.LOG_DIR = Path(tempfile.mkdtemp(prefix="yt-kids-test-"))

from core import db
from pipeline import plan, seo

GROUPS = {
    "farm animals": [f"farm{i}" for i in range(8)],
    "wild animals": [f"wild{i}" for i in range(14)],
    "sea animals": [f"sea{i}" for i in range(12)],
    "birds": [f"bird{i}" for i in range(8)],
    "insects": [f"bug{i}" for i in range(6)],
    "transport": [f"vehicle{i}" for i in range(10)],
    "fruit and vegetables": [f"food{i}" for i in range(10)],
}
ALL = [s for items in GROUPS.values() for s in items]
CLIPS = {s: {"clips": [{"id": f"{s}-a", "clip": f"https://x/{s}.mp4", "licence": "p"},
                       {"id": f"{s}-b", "clip": f"https://x/{s}2.mp4", "licence": "p"}]}
         for s in ALL}
FACTS = {s: {"facts": [{"fact": f"A {s} is here."}]} for s in ALL}
SOUNDS = {s: {"sounds": [{"id": f"snd-{s}", "title": s, "licence": "cc0",
                          "url": f"https://x/{s}.wav"}]} for s in ALL if not s.startswith(("food", "vehicle"))}
CFG = {"cards_per_video": 30}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def _plan(tmp, name, video_number):
    db.DB_PATH = tmp / f"{name}.db"
    db.init_db()
    vid = None
    for _ in range(video_number):
        vid = db.create_video("pending")
    plan.run(vid, CFG, None, None, GROUPS, clips=CLIPS, facts=FACTS, sound_book=SOUNDS,
             rng=random.Random(vid))
    return vid, db.get_video(vid), db.get_cards(vid)


def test_a_video_is_made_of_one_family(tmp):
    print("test_a_video_is_made_of_one_family")
    vid, video, cards = _plan(tmp, "family", 1)
    themes = {plan.theme_of(c["subject"], GROUPS) for c in cards}
    families = {plan.family_of(t) for t in themes}
    check(len(cards) == 30, f"thirty cards ({len(cards)})")
    check(len(families) == 1, f"all from one family ({sorted(families)})")


def test_the_title_describes_what_is_on_the_cards(tmp):
    print("test_the_title_describes_what_is_on_the_cards")
    _vid, video, cards = _plan(tmp, "title", 1)
    check(video["theme"] in ("animals", "vehicles", "food"),
          f"the recorded theme is a family, not a mixture ({video['theme']})")
    title = seo.title_for(video["theme"], len(cards), True)
    check(title.startswith("30 ") and "for Kids" in title, f"number + what + who: {title}")
    check(len(title) <= seo.MAX_TITLE, "inside YouTube's 100 characters")
    mixed = plan.dominant_theme(["farm0", "vehicle0", "food0"], GROUPS, "x")
    check(mixed == "animals and machines", "genuinely mixed cards are called a mixture")
    check(plan.dominant_theme(["farm0", "wild0"], GROUPS, "x") == "animals",
          "two animal themes are named as animals")
    check(plan.dominant_theme(["food0", "food1"], GROUPS, "x") == "fruit and vegetables",
          "one theme keeps its own name")


def test_no_clip_is_used_twice_in_a_video(tmp):
    print("test_no_clip_is_used_twice_in_a_video")
    _vid, _video, cards = _plan(tmp, "dup", 2)
    ids = [c["clip_id"] for c in cards if c["clip_id"]]
    check(len(ids) == len(set(ids)), f"{len(ids)} clips, all different")
    subjects = [c["subject"] for c in cards]
    check(len(subjects) == len(set(subjects)), "and no subject twice either")


def test_a_family_too_small_for_a_video_is_skipped(tmp):
    print("test_a_family_too_small_for_a_video_is_skipped")
    for n in range(1, 13):
        family = plan.choose_family(GROUPS, n, 30)
        check(family == "animals", f"video {n}: vehicles and food (10 each) cannot make "
                                   "thirty cards, so the family is animals")
    big = {**GROUPS, "transport": [f"v{i}" for i in range(35)]}
    seen = {plan.choose_family(big, n, 30) for n in range(1, 13)}
    check("vehicles" in seen, "once vehicles can supply thirty, they are used")


def test_the_same_video_plans_the_same_way(tmp):
    print("test_the_same_video_plans_the_same_way")
    a = _plan(tmp, "same_a", 3)[2]
    b = _plan(tmp, "same_b", 3)[2]
    check([c["subject"] for c in a] == [c["subject"] for c in b],
          "a rerun of video 3 after a failure is the same video")


def test_sounds_only_where_the_thing_makes_one(tmp):
    print("test_sounds_only_where_the_thing_makes_one")
    big = {**GROUPS, "fruit and vegetables": GROUPS["fruit and vegetables"] + ["x"] * 0}
    _vid, _video, cards = _plan(tmp, "snd", 1)
    for c in cards:
        if plan.theme_of(c["subject"], GROUPS) not in plan.SOUNDED_THEMES:
            check(not c["sound_id"], f"{c['subject']} has no sound")
    check(any(c["sound_id"] for c in cards), "and animals do")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        test_a_video_is_made_of_one_family(tmp)
        test_the_title_describes_what_is_on_the_cards(tmp)
        test_no_clip_is_used_twice_in_a_video(tmp)
        test_a_family_too_small_for_a_video_is_skipped(tmp)
        test_the_same_video_plans_the_same_way(tmp)
        test_sounds_only_where_the_thing_makes_one(tmp)
    print("ALL PLAN TESTS PASSED")
