"""Fill assets/facts.json: write several facts per subject, check each, keep what survives.

    python scripts/build_facts.py                  # every subject without enough facts
    python scripts/build_facts.py --subject whale  # one, repeatable
    python scripts/build_facts.py --refresh        # everything, from scratch

Run when a new theme is added, like the clip catalogue, and for the same reason: the daily run
must not invent a fact nobody has checked. Three of the first forty the model wrote were false
and all three passed every structural rule, so the check happens once, here, where a rejected
fact costs a retry rather than a published video.

Refusals are kept in the file with the judge's reason. A check nobody can read is a check
nobody can argue with, and the judge is a language model - it will be wrong sometimes, and
when it is, the record is what shows it.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config, factcheck
from core.llm import LLMError
from pipeline import cards

FACTS = ROOT / "assets" / "facts.json"
WANT_PER_SUBJECT = 4
ROUNDS = 8               # how many times a subject is asked before giving up on filling it


def load(path=FACTS):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}


def save(data, path=FACTS):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def fill(subject, account, token, have, want=WANT_PER_SUBJECT, rounds=ROUNDS):
    """(kept, refused) for one subject, asking again until it has `want` or runs out of tries."""
    kept = list(have.get("facts", []))
    refused = list(have.get("refused", []))
    seen = {f["fact"].lower() for f in kept} | {f["fact"].lower() for f in refused}
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for _ in range(rounds):
        if len(kept) >= want:
            break
        # Asked for the subject several times over, because one call returns one fact per
        # subject; the variety comes from asking again rather than from asking for a list,
        # which produced four rewordings of the same sentence.
        said = [f["fact"] for f in kept] + [f["fact"] for f in refused]
        try:
            facts, _failed = cards.write_facts([subject], account, token, avoid=said)
        except LLMError as e:
            print(f"    could not write: {str(e)[:80]}")
            break
        fact = facts.get(subject)
        if not fact or fact.lower() in seen:
            continue
        if cards.is_near_duplicate(fact, [f["fact"] for f in kept]):
            seen.add(fact.lower())
            continue
        seen.add(fact.lower())
        verdict = factcheck.check(subject, fact, account, token)
        if verdict["passed"] is True:
            kept.append({"fact": fact, "checked": stamp})
        elif verdict["passed"] is False:
            refused.append({"fact": fact, "why": verdict["why"], "checked": stamp})
        else:
            print(f"    judge unreachable, {fact!r} left out")
    return kept, refused


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", action="append")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--want", type=int, default=WANT_PER_SUBJECT)
    args = parser.parse_args(argv)

    account, token, _ = config.credentials()
    if not (account and token):
        print("needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in .env")
        return 2

    groups = json.loads((ROOT / "assets" / "subjects.json").read_text(encoding="utf-8"))
    all_subjects = [s for g in groups.values() for s in g]
    data = {} if args.refresh else load()
    wanted = args.subject or [s for s in all_subjects
                              if len(data.get(s, {}).get("facts", [])) < args.want]
    if not wanted:
        print(f"nothing to do: every subject has {args.want} checked facts")
        return 0

    print(f"{len(wanted)} subject(s) to fill, {args.want} checked facts each")
    for subject in wanted:
        kept, refused = fill(subject, account, token, data.get(subject, {}), args.want)
        data[subject] = {"facts": kept, "refused": refused}
        save(data)
        shown = kept[0]["fact"] if kept else "NOTHING"
        print(f"  {subject:12} {len(kept)} kept, {len(refused)} refused | {shown[:46]}",
              flush=True)

    enough = [s for s in all_subjects if len(data.get(s, {}).get("facts", [])) >= 1]
    refused_total = sum(len(v.get("refused", [])) for v in data.values())
    print(f"\n{len(enough)} of {len(all_subjects)} subjects have at least one checked fact; "
          f"{refused_total} fact(s) refused along the way")
    print(f"written to {FACTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
