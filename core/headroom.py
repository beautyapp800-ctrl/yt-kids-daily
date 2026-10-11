"""How many more videos the catalogues can supply before they start repeating themselves.

A video needs cards_per_video subjects, and a subject can only be used once a video has a clip,
a checked fact and - where the thing makes a sound - a checked sound. Sixty subjects is two
videos. After that the plan reuses subjects, and a weekly viewer sees the same lion again.

So the channel's real supply is not the queue on YouTube, it is this number: the subjects that
are complete, and not on a card in the last few videos, divided by the cards one video takes.
The daily self-check warns when it falls, and the grow job exists to raise it.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECENT_VIDEOS = 6


def _load(name):
    path = ROOT / "assets" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def complete_subjects():
    """Subjects with a verified clip and a checked fact: everything a card needs but a sound,
    which is optional because many things make none."""
    clips, facts = _load("clips.json"), _load("facts.json")
    return sorted(s for s, v in clips.items()
                  if v.get("clips") and (facts.get(s) or {}).get("facts"))


def fresh_subjects(recently_used):
    return [s for s in complete_subjects() if s not in set(recently_used)]


def videos_left(recently_used, cards_per_video):
    """Whole videos' worth of subjects not used in the last few videos."""
    return len(fresh_subjects(recently_used)) // max(int(cards_per_video), 1)


def thinnest_themes(groups, recently_used, count=2):
    """The themes with the fewest fresh subjects, the ones to grow first."""
    fresh = set(fresh_subjects(recently_used))
    ranked = sorted(groups, key=lambda t: sum(1 for s in groups[t] if s in fresh))
    return ranked[:count]
