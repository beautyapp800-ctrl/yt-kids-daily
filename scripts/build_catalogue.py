"""Fill assets/clips.json: search, verify with the model, keep what it confirms.

    python scripts/build_catalogue.py                    # every subject not done yet
    python scripts/build_catalogue.py --subject whale    # one, repeatable
    python scripts/build_catalogue.py --refresh          # everything, from scratch

Run when a new theme is added. It is the only part of the project that searches a stock
library; the daily run reads the catalogue and never searches, because search returns a clip
tagged "train" that shows a bridge at sunset and nothing downstream can notice.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core import vision
from pipeline import catalogue
import stock_probe

WORK = ROOT / "data" / "candidate-frames"


def credentials():
    import os
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if k.strip() == "CLOUDFLARE_ACCOUNT_ID" and not account:
                    account = v
                if k.strip() == "CLOUDFLARE_API_TOKEN" and not token:
                    token = v
    return account, token


def search_term(subject):
    """What to type into the library for this subject.

    Usually the subject's own name. Sometimes the name means something else to a stock
    library: "turkey" returned Istanbul twelve frames running - a man, a city, a bridge, a
    mosque - and the subject was filed as having no footage. The exceptions live in
    assets/subject-pool.json next to the subjects themselves.
    """
    try:
        book = json.loads((ROOT / "assets" / "subject-pool.json").read_text(encoding="utf-8"))
        return (book.get("search_terms") or {}).get(subject, subject)
    except Exception:                                            # noqa: BLE001
        return subject


def search(subject, key, wanted=catalogue.CANDIDATES_PER_SUBJECT):
    """Every Pixabay hit that passes the cheap checks, before the model is spent on it."""
    import urllib.parse
    url = ("https://pixabay.com/api/videos/?per_page=60&video_type=film&safesearch=true&q="
           + urllib.parse.quote(search_term(subject)) + "&key=" + key)
    data = stock_probe.get_json(url)
    # Tag matching used to be the gate. It was a crutch from before there was a model that
    # could look at the frame, and as a gate it costs more than it saves: "whale" left one
    # single candidate, and a subject with one clip cannot fill two cards in a video without
    # repeating itself. It is now only an ordering - hits whose tags name the subject are put
    # to the model first - and the model decides, which is what it is for.
    ranked = sorted(data.get("hits", []),
                    key=lambda v: not stock_probe._relevant(search_term(subject), v))
    out = []
    for v in ranked:
        if v.get("isAiGenerated") or v.get("isGRated") is False:
            continue
        best = stock_probe.best_stream(list((v.get("videos") or {}).values()))
        if not best or (v.get("duration") or 0) < stock_probe.MIN_SECONDS:
            continue
        out.append({"id": v["id"], "url": v.get("pageURL"), "seconds": v["duration"],
                    "width": best["width"], "licence": "Pixabay Content Licence",
                    "attribution_required": False, "thumbnail": best.get("thumbnail"),
                    # The stream that is actually big enough, not the small one. The first
                    # version stored videos.small or videos.tiny - 960x540 or 640x360 - and
                    # the render then upscaled them to 1080p: worse pictures, and one 640x360
                    # clip took 146 seconds to render against 8 for the others.
                    "clip": best.get("url")})
        if len(out) >= wanted:
            break
    return out


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", action="append")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)

    account, token = credentials()
    key = stock_probe.key_for("pixabay")
    if not (account and token and key):
        print("needs PIXABAY_API_KEY, CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in .env")
        return 2

    groups = json.loads((ROOT / "assets" / "subjects.json").read_text(encoding="utf-8"))
    all_subjects = [s for g in groups.values() for s in g]
    data = {} if args.refresh else catalogue.load()
    wanted = args.subject or [s for s in all_subjects if s not in data]
    if not wanted:
        print(f"nothing to do: all {len(all_subjects)} subjects are in the catalogue")
        return 0

    print(f"{len(wanted)} subject(s) to verify")
    unreachable = []
    for subject in wanted:
        try:
            hits = search(subject, key)
        except Exception as e:                                   # noqa: BLE001
            # NOT recorded as a subject with no clips. The network went away during the
            # first full build and fourteen subjects came back "search failed", which the
            # summary then counted as absent footage - the same mistake the coverage probe
            # made with HTTP 429. A question that could not be asked has no answer, in
            # either direction.
            print(f"  {subject:14} COULD NOT ASK: {str(e)[:60]}")
            unreachable.append(subject)
            continue
        kept, rejected = catalogue.verify_subject(subject, hits, account, token, WORK, vision)
        data[subject] = {"clips": kept, "rejected": rejected,
                         "candidates_seen": len(hits)}
        best = f"{kept[0]['prominence']:.2f}" if kept else "-"
        print(f"  {subject:14} {len(kept)} kept of {len(hits)} looked at, "
              f"best framing {best}"
              f"{'  <- NOTHING, will be drawn' if not kept else ''}", flush=True)
        catalogue.save(data)

    covered = [s for s in all_subjects if data.get(s, {}).get("clips")]
    asked = len(all_subjects) - len(unreachable)
    print(f"\n{len(covered)} of {asked} subjects asked about have at least one "
          f"verified clip ({100 * len(covered) / max(asked, 1):.0f}%)")
    if unreachable:
        print(f"COULD NOT ASK about {len(unreachable)}, so they are in neither figure "
              f"and have no entry: {', '.join(unreachable)}")
    thin = [s for s in covered if len(data[s]["clips"]) < 2]
    if thin:
        print(f"only one clip, so two cards in a video could collide: {', '.join(thin)}")
    print(f"written to {catalogue.CATALOGUE}")
    # Non-zero so a half-finished build cannot be mistaken for a complete one.
    return 1 if unreachable else 0


if __name__ == "__main__":
    sys.exit(main())
