"""The daily run must not ask a model anything it could have asked once.

Run: python tests/test_daily_cost.py

The free Cloudflare allowance is 10,000 neurons a day and a run died halfway through when it
ran out. The cause was architectural, not accidental: the plan stage was judging three or four
sound candidates for every card, which is a hundred model calls a day for answers that never
change - does a cow moo, is this recording really a dolphin.

Clips, facts and sounds are all catalogues now, each checked once when it is added. This test
holds that line, because the next thing anybody adds to the plan stage will be tempting to
check live.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.logger
core.logger.LOG_DIR = Path(tempfile.mkdtemp(prefix="yt-kids-test-"))


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def test_the_plan_stage_calls_no_model():
    print("test_the_plan_stage_calls_no_model")
    source = (ROOT / "pipeline" / "plan.py").read_text(encoding="utf-8")
    for forbidden, what in [("soundcheck.", "the sound judge"),
                            ("write_facts", "the fact writer"),
                            ("complete_json", "the language model"),
                            ("vision.", "the picture checker")]:
        check(forbidden not in source, f"plan.py does not call {what}")


def test_everything_the_plan_needs_comes_from_a_catalogue():
    print("test_everything_the_plan_needs_comes_from_a_catalogue")
    source = (ROOT / "pipeline" / "plan.py").read_text(encoding="utf-8")
    for loader in ("_load_facts", "_load_sounds", "catalogue.load"):
        check(loader in source, f"plan.py reads {loader}")
    for name in ("clips.json", "facts.json", "sounds.json"):
        path = ROOT / "assets" / name
        check(path.exists() or name == "sounds.json",
              f"assets/{name} is the catalogue the daily run reads"
              + (" (not built yet)" if not path.exists() else ""))


def test_a_silent_subject_is_recorded_rather_than_retried():
    print("test_a_silent_subject_is_recorded_rather_than_retried")
    import json
    path = ROOT / "assets" / "sounds.json"
    if not path.exists():
        print("  (skipped: the sound catalogue is not built yet)")
        return
    book = json.loads(path.read_text(encoding="utf-8"))
    silent = [s for s, v in book.items() if not v.get("sounds")]
    for subject in silent:
        check("silent" in book[subject],
              f"{subject} is marked silent rather than left looking unfinished")


if __name__ == "__main__":
    test_the_plan_stage_calls_no_model()
    test_everything_the_plan_needs_comes_from_a_catalogue()
    test_a_silent_subject_is_recorded_rather_than_retried()
    print("ALL DAILY COST TESTS PASSED")
