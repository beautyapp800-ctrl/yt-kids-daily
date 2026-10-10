"""Does the fact checker catch false facts? Measured, before it is trusted.

    python scripts/fact_measure.py

Two sets go in:

  the real ones   40 facts the model actually wrote for the subject list, read and judged by
                  eye first and recorded in data/fact-verdict.json. Two of them are false and
                  one is misleading, which is the error rate this is meant to stop.
  the planted     14 false statements written to be plausible and to pass every structural
                  rule - right length, names the thing, no measurements, no large numbers.
                  Without these there would be too few false facts to measure anything on.

The numbers printed are the two that matter: how many false facts are caught, and how many
true ones are thrown away. The second is nearly free here - a refused fact is just rewritten -
so the checker should be set to catch, not to be fair.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config, factcheck

VERDICT = ROOT / "data" / "fact-verdict.json"
OUT = ROOT / "data" / "fact-measure.json"

# Plausible, structurally perfect, and wrong. Every one of these passes pipeline/cards.py.
PLANTED = [
    ("octopus", "An octopus has six arms."),
    ("spider", "A spider has six legs."),
    ("bee", "A bee has eight legs."),
    ("butterfly", "A butterfly has eight wings."),
    ("penguin", "A penguin lives at the North Pole."),
    ("whale", "A whale is a very big fish."),
    ("shark", "A shark is a mammal."),
    ("zebra", "A zebra has blue stripes."),
    ("owl", "An owl sleeps at night."),
    ("bat", "A bat is a kind of bird."),
    ("cow", "A cow eats meat."),
    ("duck", "A duck has four legs."),
    ("starfish", "A starfish is a fish."),
    ("elephant", "An elephant drinks through its trunk."),
]


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    account, token, _ = config.credentials()
    if not (account and token):
        print("needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN")
        return 2

    human = json.loads(VERDICT.read_text(encoding="utf-8"))
    rows = []
    for subject, fact in [(s, f["fact"]) for s, f in human.items()]:
        rows.append((subject, fact, human[subject]["true"], "written"))
    for subject, fact in PLANTED:
        rows.append((subject, fact, False, "planted"))

    results = []
    for subject, fact, truth, source in rows:
        got = factcheck.check(subject, fact, account, token)
        results.append({"subject": subject, "fact": fact, "actually_true": truth,
                        "source": source, **got})
        mark = {True: "passed", False: "REJECTED", None: "unknown"}[got["passed"]]
        flag = "" if (got["passed"] is truth) else "   <-- wrong"
        print(f"  {subject:11} {mark:9} truth={str(truth):5} {fact[:44]:46}{flag}", flush=True)

    false_ones = [r for r in results if r["actually_true"] is False]
    true_ones = [r for r in results if r["actually_true"] is True]
    caught = [r for r in false_ones if r["passed"] is False]
    lost = [r for r in true_ones if r["passed"] is False]
    print(f"\ncaught {len(caught)} of {len(false_ones)} false facts "
          f"({100 * len(caught) / max(len(false_ones), 1):.0f}%)")
    missed = [r for r in false_ones if r["passed"] is not False]
    if missed:
        print("  let through: " + "; ".join(f'"{r["fact"]}"' for r in missed))
    print(f"lost   {len(lost)} of {len(true_ones)} true facts "
          f"({100 * len(lost) / max(len(true_ones), 1):.0f}%)")
    if lost:
        print("  wrongly rejected: " + "; ".join(f'"{r["fact"]}" ({r["why"][:60]})'
                                                 for r in lost))
    written_false = [r for r in false_ones if r["source"] == "written"]
    print(f"\nof the 40 the model wrote by itself, {len(written_false)} were false; "
          f"the checker caught {sum(1 for r in written_false if r['passed'] is False)}")
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
