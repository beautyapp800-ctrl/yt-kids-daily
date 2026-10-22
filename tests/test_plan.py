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
CFG = {"cards_per_video": 30, "min_theme_cards": 6}


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


def test_a_video_is_one_theme(tmp):
    print("test_a_video_is_one_theme")
    _vid, video, cards = _plan(tmp, "theme", 1)
    themes = {plan.theme_of(c["subject"], GROUPS) for c in cards}
    check(len(themes) == 1, f"every card is from one theme ({themes})")
    check(video["theme"] in GROUPS, f"and the video is recorded as that theme ({video['theme']})")
    check(len(cards) <= len(GROUPS[video["theme"]]),
          f"{len(cards)} cards from a theme of {len(GROUPS[video['theme']])}: never padded "
          "from elsewhere")


def test_three_videos_running_are_not_the_same_video(tmp):
    print("test_three_videos_running_are_not_the_same_video")
    # The fault this was written for: videos 1, 2 and 3 were all "30 Animals for Kids" and
    # shared twenty subjects out of thirty.
    db.DB_PATH = tmp / "three.db"
    db.init_db()
    made = []
    for _ in range(3):
        vid = db.create_video("pending")
        plan.run(vid, CFG, None, None, GROUPS, clips=CLIPS, facts=FACTS, sound_book=SOUNDS,
                 rng=random.Random(vid))
        video = db.get_video(vid)
        subs = {c["subject"] for c in db.get_cards(vid)}
        title = seo.title_for(video["theme"], len(subs), True, vid,
                              [v["seo_title"] for v in db.recent_videos(10)])
        db.update_video(vid, seo_title=title)
        made.append((video["theme"], subs, title))
    themes = [t for t, _s, _ti in made]
    check(len(set(themes)) == 3, f"three different themes: {themes}")
    for i in range(3):
        for j in range(i + 1, 3):
            shared = made[i][1] & made[j][1]
            check(not shared, f"videos {i+1} and {j+1} share no subject at all ({shared})")
    titles = [t for _th, _s, t in made]
    check(len(set(titles)) == 3, "and three different titles: " + " / ".join(titles))


def test_a_theme_rests_before_coming_round_again(tmp):
    print("test_a_theme_rests_before_coming_round_again")
    sizes = {t: len(v) for t, v in GROUPS.items()}
    recent, picked = [], []
    for n in range(len(GROUPS) * 2):
        theme = plan.choose_theme(GROUPS, recent, sizes, floor=6)
        picked.append(theme)
        recent.insert(0, {"theme": theme})
    check(len(set(picked[:len(GROUPS)])) == len(GROUPS),
          f"the first pass uses every theme once: {picked[:len(GROUPS)]}")
    gaps = [j - i for i, t in enumerate(picked) for j in range(i + 1, len(picked)) if picked[j] == t]
    check(min(gaps) >= len(GROUPS) - 1 if gaps else True,
          f"and no theme comes back sooner than {len(GROUPS) - 1} videos later "
          f"(smallest gap {min(gaps) if gaps else '-'})")


def test_a_theme_too_thin_for_a_video_is_not_used(tmp):
    print("test_a_theme_too_thin_for_a_video_is_not_used")
    sizes = {"birds": 4, "insects": 3, "wild animals": 14}
    check(plan.choose_theme(GROUPS, [], sizes, floor=10) == "wild animals",
          "only the theme that can fill a video is chosen")
    try:
        plan.choose_theme(GROUPS, [], {"birds": 4, "insects": 3}, floor=10)
    except RuntimeError as e:
        check("no theme has 10" in str(e) and "grow" in str(e),
              f"and when none can, it says so and names the largest: {str(e)[:80]}")
        return
    raise AssertionError("a video was planned from a theme that cannot fill it")


def test_a_subject_rests_five_videos(tmp):
    print("test_a_subject_rests_five_videos")
    rng = random.Random(1)
    big = {"birds": [f"bird{i}" for i in range(40)]}
    distances = {"bird0": 1, "bird1": 3, "bird2": 5, "bird3": 6}
    chosen = plan.choose_subjects(big, "birds", 30, distances, rng)
    for name, d in distances.items():
        if d <= plan.SUBJECT_REST:
            check(name not in chosen, f"{name}, used {d} video(s) ago, is held back")
    check("bird3" in chosen, "bird3, used 6 videos ago, is free to come back")


def test_when_a_theme_is_small_the_held_back_return_oldest_first(tmp):
    print("test_when_a_theme_is_small_the_held_back_return_oldest_first")
    small = {"insects": [f"bug{i}" for i in range(8)]}
    distances = {f"bug{i}": (i % 5) + 1 for i in range(8)}
    chosen = plan.choose_subjects(small, "insects", 8, distances, random.Random(2))
    check(len(chosen) == 8, "a theme of eight still fills eight cards")
    came_back = [s for s in chosen if distances.get(s, 99) <= plan.SUBJECT_REST]
    oldest = sorted(came_back, key=lambda s: -distances[s])
    check(came_back and came_back[0] == oldest[0] or not came_back,
          "and the ones that come back early are the ones used longest ago")


def test_no_clip_is_used_twice_in_a_video(tmp):
    print("test_no_clip_is_used_twice_in_a_video")
    _vid, _video, cards = _plan(tmp, "dup", 2)
    ids = [c["clip_id"] for c in cards if c["clip_id"]]
    check(len(ids) == len(set(ids)), f"{len(ids)} clips, all different")
    subjects = [c["subject"] for c in cards]
    check(len(subjects) == len(set(subjects)), "and no subject twice either")


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
        test_a_video_is_one_theme(tmp)
        test_three_videos_running_are_not_the_same_video(tmp)
        test_a_theme_rests_before_coming_round_again(tmp)
        test_a_theme_too_thin_for_a_video_is_not_used(tmp)
        test_a_subject_rests_five_videos(tmp)
        test_when_a_theme_is_small_the_held_back_return_oldest_first(tmp)
        test_no_clip_is_used_twice_in_a_video(tmp)
        test_the_same_video_plans_the_same_way(tmp)
        test_sounds_only_where_the_thing_makes_one(tmp)
    print("ALL PLAN TESTS PASSED")
