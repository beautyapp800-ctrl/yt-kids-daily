"""Does the classifier actually catch what my eyes caught?

    python scripts/vision_measure.py

The 59 frames in data/human-verdict.json were judged by eye first - 29 strong, 18 weak, 12 not
the subject at all. This runs the verifier over the same 59 and prints the only two numbers
that decide whether the catalogue can grow by itself:

    caught   of the 12 frames that show the wrong thing, how many the model rejects
    lost     of the 29 strong frames, how many the model wrongly rejects

The second number is the expensive one. A verifier that throws away good footage makes the
catalogue smaller every week, and nobody notices until a video is half drawings. So the bar is
asymmetric: missing a bad frame costs one poor card, rejecting a good one costs a subject.

Weak frames are reported separately and counted neither way. They are the honest grey area -
a cow as a speck in an aerial shot genuinely is a cow - and a verifier has no business ruling
on framing, only on subject.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import vision

FRAMES = Path(os.environ.get("KIDS_FRAMES",
                             r"C:\Users\PC\AppData\Local\Temp\kidsframes\pixabay"))
VERDICT = ROOT / "data" / "human-verdict.json"
OUT = ROOT / "data" / "vision-measure.json"


def credentials():
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if k.strip() == "CLOUDFLARE_ACCOUNT_ID" and not account:
                account = v
            if k.strip() == "CLOUDFLARE_API_TOKEN" and not token:
                token = v
    return account, token


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-describer", action="store_true",
                        help="classifier only; much faster, and the honest floor")
    parser.add_argument("--frames", default=str(FRAMES))
    args = parser.parse_args(argv)

    account, token = credentials()
    if not account or not token:
        print("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are not set.\n"
              "This project has its own Cloudflare account, separate from yt-factory, so the "
              "measurement cannot borrow that one's quota. Put both in C:\\yt-kids\\.env.")
        return 2

    human = json.loads(VERDICT.read_text(encoding="utf-8"))["verdict"]
    frames = Path(args.frames)
    results, missing = {}, []
    for subject, mine in sorted(human.items()):
        frame = frames / (subject.replace(" ", "_") + ".jpg")
        if not frame.exists():
            missing.append(subject)
            continue
        got = vision.verify(frame, subject, account, token,
                            use_describer=not args.no_describer)
        results[subject] = {"human": mine, **got}
        mark = {True: "shows it", False: "REJECTED", None: "could not ask"}[got["shows_it"]]
        top = ", ".join(f"{l} {s:.2f}" for l, s in got["labels"][:2])
        print(f"  {subject:12} human={mine:6} model={mark:14} {top[:52]}"
              f"{' | ' + got['description'][:28] if got['description'] else ''}", flush=True)

    wrong = [s for s, r in results.items() if r["human"] == "wrong"]
    strong = [s for s, r in results.items() if r["human"] == "strong"]
    weak = [s for s, r in results.items() if r["human"] == "weak"]
    caught = [s for s in wrong if results[s]["shows_it"] is False]
    lost = [s for s in strong if results[s]["shows_it"] is False]
    weak_kept = [s for s in weak if results[s]["shows_it"] is True]

    print(f"\ncaught {len(caught)} of {len(wrong)} frames that show the wrong thing"
          f" ({', '.join(sorted(caught)) or 'none'})")
    print(f"missed {len(wrong) - len(caught)}"
          f" ({', '.join(sorted(s for s in wrong if s not in caught)) or 'none'})")
    print(f"lost   {len(lost)} of {len(strong)} good frames"
          f" ({', '.join(sorted(lost)) or 'none'})")
    print(f"weak frames kept: {len(weak_kept)} of {len(weak)}")
    for name, key in (("classifier", "by_classifier"), ("describer", "by_describer")):
        c = sum(1 for s in wrong if results[s].get(key) is False)
        l = sum(1 for s in strong if results[s].get(key) is False)
        asked = sum(1 for r in results.values() if r.get(key) is not None)
        if asked:
            print(f"  {name:10} on its own: caught {c} of {len(wrong)}, lost {l} of {len(strong)}")
    if missing:
        print(f"no frame on disk for: {', '.join(missing)}")

    OUT.write_text(json.dumps({"caught": caught, "lost": lost, "results": results}, indent=2),
                   encoding="utf-8")
    print(f"\nwritten to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
