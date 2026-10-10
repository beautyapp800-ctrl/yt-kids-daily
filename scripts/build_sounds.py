"""Fill assets/sounds.json: find each subject's real sound, judge it, keep what survives.

    python scripts/build_sounds.py                 # every subject without enough sounds
    python scripts/build_sounds.py --subject cow   # one, repeatable

The third catalogue, and it exists for the same two reasons as the others.

The first is correctness: taking the first search hit put the click of a push-button torch on
the dolphin card. Judging costs a model call, and a model call in the daily run is a model
call that can fail on the day it matters.

The second is the one that stopped a run dead. The free Cloudflare allowance is 10,000
neurons a day, and judging sounds for twenty-five cards at three or four candidates each is
seventy-five to a hundred model calls - every day, for an answer that does not change. "Does a
cow moo" is not a question that needs asking daily. Checked once here, the daily run spends
nothing on it at all.

Silence is a real answer and is recorded as one: sharks, octopuses and seahorses do not make a
sound, and a subject with an empty list is not retried every time the builder runs.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config, sounds, soundcheck
from pipeline.plan import SOUNDED_THEMES, _sound_queries, theme_of

CATALOGUE = ROOT / "assets" / "sounds.json"
KEEP = 2                 # a spare, so one dead link does not silence a card


def load(path=CATALOGUE):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}


def save(data, path=CATALOGUE):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def fill(subject, account, token, keep=KEEP):
    """(kept, refused) for one subject."""
    found = sounds.search_many(subject, _sound_queries(subject))
    kept, refused = [], []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for record in found[:10]:
        verdict = soundcheck.check(subject, record, account, token)
        if verdict["ok"] is True:
            kept.append({**record, "is": verdict["why"], "checked": stamp})
            if len(kept) >= keep:
                break
        elif verdict["ok"] is False:
            refused.append({"title": record.get("title"), "why": verdict["why"]})
    return kept, refused, len(found)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", action="append")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)

    account, token, _ = config.credentials()
    if not (account and token):
        print("needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in .env")
        return 2

    groups = json.loads((ROOT / "assets" / "subjects.json").read_text(encoding="utf-8"))
    sounded = [s for theme, items in groups.items() if theme in SOUNDED_THEMES for s in items]
    data = {} if args.refresh else load()
    wanted = args.subject or [s for s in sounded if s not in data]
    if not wanted:
        print(f"nothing to do: all {len(sounded)} subjects that can have a sound are done")
        return 0

    print(f"{len(wanted)} subject(s) to check")
    unreachable = []
    for subject in wanted:
        try:
            kept, refused, seen = fill(subject, account, token)
        except Exception as e:                                   # noqa: BLE001
            # Not written as "no sound": a question that could not be asked has no answer.
            print(f"  {subject:12} COULD NOT ASK: {str(e)[:60]}")
            unreachable.append(subject)
            continue
        data[subject] = {"sounds": kept, "refused": refused, "candidates_seen": seen,
                         "silent": not kept and seen > 0}
        note = kept[0]["title"][:40] if kept else (
            "silent - nothing usable exists" if seen else "no candidates at all")
        print(f"  {subject:12} {len(kept)} kept, {len(refused)} refused | {note}", flush=True)
        save(data)

    with_sound = [s for s in sounded if data.get(s, {}).get("sounds")]
    silent = [s for s in sounded if s in data and not data[s].get("sounds")]
    asked = len(sounded) - len(unreachable)
    print(f"\n{len(with_sound)} of {asked} subjects asked about have a checked sound "
          f"({100 * len(with_sound) / max(asked, 1):.0f}%)")
    if silent:
        print(f"genuinely silent: {', '.join(silent)}")
    if unreachable:
        print(f"COULD NOT ASK about {len(unreachable)}: {', '.join(unreachable)}")
    print(f"written to {CATALOGUE}")
    return 1 if unreachable else 0


if __name__ == "__main__":
    sys.exit(main())
