"""Offline tests for the clip catalogue. Run: python tests/test_catalogue.py

No network and no model: the catalogue is a fixture. What is tested is the rule a viewer
would notice being broken - the same picture twice in one video - and the ordering that puts
the best-framed clip first.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.logger
core.logger.LOG_DIR = Path(tempfile.mkdtemp(prefix="yt-kids-test-"))

from pipeline import catalogue


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def clip(cid, prominence=1.0):
    return {"id": cid, "prominence": prominence, "licence": "Pixabay Content Licence"}


FIXTURE = {
    # The real case: one frame of a rooster honestly answers both, and the model confirms it
    # for both, because it IS a rooster and a rooster IS a chicken.
    "chicken": {"clips": [clip(100), clip(101)]},
    "rooster": {"clips": [clip(100), clip(102)]},
    "whale": {"clips": [clip(200)]},
    "dolphin": {"clips": [clip(200)]},          # only the one clip, and it is shared
    "ant": {"clips": []},                        # nothing was confirmed; it gets drawn
}


def test_a_clip_is_never_used_twice_in_one_video():
    print("test_a_clip_is_never_used_twice_in_one_video")
    picked = dict(catalogue.pick_clips(["chicken", "rooster"], FIXTURE))
    check(picked["chicken"]["id"] == 100, "the first card takes the best clip")
    check(picked["rooster"]["id"] == 102,
          "the second card takes a different one, though 100 is its best too")
    ids = [c["id"] for c in picked.values() if c]
    check(len(ids) == len(set(ids)), "no clip appears twice in the video")


def test_a_subject_with_nothing_left_is_drawn_rather_than_repeated():
    print("test_a_subject_with_nothing_left_is_drawn_rather_than_repeated")
    picked = dict(catalogue.pick_clips(["whale", "dolphin"], FIXTURE))
    check(picked["whale"]["id"] == 200, "the first of the two takes the only clip")
    check(picked["dolphin"] is None,
          "and the second gets nothing, so the card is drawn - showing the same whale twice "
          "and calling it a dolphin is worse than a picture")


def test_order_follows_the_order_asked_for():
    print("test_order_follows_the_order_asked_for")
    picked = catalogue.pick_clips(["rooster", "chicken"], FIXTURE)
    check([s for s, _ in picked] == ["rooster", "chicken"], "the subjects come back in order")
    check(picked[0][1]["id"] == 100 and picked[1][1]["id"] == 101,
          "and whichever is asked for first gets the shared clip")


def test_exclusions_can_be_carried_in():
    print("test_exclusions_can_be_carried_in")
    picked = dict(catalogue.pick_clips(["chicken"], FIXTURE, used={100}))
    check(picked["chicken"]["id"] == 101, "a clip excluded by the caller is skipped")


def test_a_subject_with_no_clips_asks_for_a_drawing():
    print("test_a_subject_with_no_clips_asks_for_a_drawing")
    check(dict(catalogue.pick_clips(["ant"], FIXTURE))["ant"] is None,
          "a subject the model confirmed nothing for returns None")
    check(dict(catalogue.pick_clips(["newt"], FIXTURE))["newt"] is None,
          "and so does one that is not in the catalogue at all")


def test_the_best_framed_clip_is_first():
    print("test_the_best_framed_clip_is_first")
    kept = sorted([clip(1, 0.2), clip(2, 0.99), clip(3, 0.5)], key=lambda c: -c["prominence"])
    check([c["id"] for c in kept] == [2, 3, 1],
          "clips are ordered by how much of the frame the subject fills")
    check(catalogue.prominence([("tiger shark", 0.8), ("surfboard", 0.1)], "shark",
                               lambda s, l: s in l) == 0.8,
          "prominence reads the score of the label that matches, not the top one")
    check(catalogue.prominence([("surfboard", 0.9)], "shark", lambda s, l: s in l) == 0.0,
          "and is zero when nothing matches")


if __name__ == "__main__":
    test_a_clip_is_never_used_twice_in_one_video()
    test_a_subject_with_nothing_left_is_drawn_rather_than_repeated()
    test_order_follows_the_order_asked_for()
    test_exclusions_can_be_carried_in()
    test_a_subject_with_no_clips_asks_for_a_drawing()
    test_the_best_framed_clip_is_first()
    print("ALL CATALOGUE TESTS PASSED")
