"""Offline tests for the label matching. Run: python tests/test_vision_match.py

No network: the model is not called. What is tested is the table between what a classifier
says and what we asked for, which is where a verifier quietly goes wrong - a synonym list
that is too generous passes a surfboard as a shark, and one that is too strict throws away
every good clip of a lorry because ImageNet calls it a trailer truck.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.logger
core.logger.LOG_DIR = Path(tempfile.mkdtemp(prefix="yt-kids-test-"))

from core import vision


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def test_every_subject_has_a_synonym_entry():
    print("test_every_subject_has_a_synonym_entry")
    groups = json.loads((ROOT / "assets" / "subjects.json").read_text(encoding="utf-8"))
    subjects = [s for g in groups.values() for s in g]
    missing = [s for s in subjects if s not in vision.SYNONYMS]
    check(not missing, f"all {len(subjects)} subjects are in the table ({missing})")


def test_imagenet_labels_match_the_subject_they_mean():
    print("test_imagenet_labels_match_the_subject_they_mean")
    for subject, label in [("shark", "tiger shark, galeocerdo cuvieri"), ("airplane", "airliner"),
                           ("train", "electric locomotive"), ("fire truck", "fire engine"),
                           ("cow", "ox"), ("chicken", "hen"), ("sea turtle", "loggerhead turtle"),
                           ("whale", "grey whale, gray whale"), ("school bus", "minibus")]:
        check(vision.names_subject(subject, label), f"{label!r} counts as {subject}")


def test_the_frames_that_fooled_the_tags_do_not_fool_this():
    print("test_the_frames_that_fooled_the_tags_do_not_fool_this")
    # Every one of these is a real clip Pixabay returned for that subject.
    for subject, label in [("shark", "surfboard"), ("octopus", "carousel, merry-go-round"),
                           ("orange", "rapeseed"), ("carrot", "daisy"),
                           ("school bus", "coral reef"), ("train", "lakeside, lakeshore"),
                           ("police car", "mountain road"),
                           ("motorcycle", "mountain bike, all-terrain bike"),
                           ("starfish", "sandbar, sand bar")]:
        check(not vision.names_subject(subject, label),
              f"{label!r} does not count as {subject}")


def test_a_low_score_guess_is_not_evidence():
    print("test_a_low_score_guess_is_not_evidence")
    check(vision.MIN_SCORE > 0, "there is a floor on the classifier's confidence")
    check(vision.TOP_N >= 3, "and more than one guess is looked at")


def test_a_model_that_falls_over_does_not_stop_the_pipeline():
    print("test_a_model_that_falls_over_does_not_stop_the_pipeline")
    real = vision.classify, vision.describe

    def boom(*a, **k):
        raise vision.VisionError("service down")

    vision.classify = vision.describe = boom
    try:
        out = vision.verify(Path(__file__), "whale", "acct", "tok")
    finally:
        vision.classify, vision.describe = real
    check(out["shows_it"] is None, "with no model answer the verdict is 'unknown', not 'no'")
    check(len(out["errors"]) == 2, "and both failures are recorded rather than swallowed")


if __name__ == "__main__":
    test_every_subject_has_a_synonym_entry()
    test_imagenet_labels_match_the_subject_they_mean()
    test_the_frames_that_fooled_the_tags_do_not_fool_this()
    test_a_low_score_guess_is_not_evidence()
    test_a_model_that_falls_over_does_not_stop_the_pipeline()
    print("ALL VISION MATCH TESTS PASSED")
