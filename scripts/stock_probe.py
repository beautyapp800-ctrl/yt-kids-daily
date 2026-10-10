"""How much of the subject list can be filmed rather than drawn.

    python scripts/stock_probe.py                 # every source that has a key
    python scripts/stock_probe.py --source commons

This is the measurement the whole shape of the project rests on. A real whale swimming beats
any drawing of one for a two-year-old, so footage is the first choice and our own pictures are
the fallback - but only the actual coverage says how big that fallback has to be, and guessing
it would mean either writing a picture pipeline nobody needs or discovering halfway through a
video that a third of its subjects have nothing to show.

A subject counts as covered only if a clip is found that could really be used: the search has
to return a result whose licence allows commercial use with no attribution burden we cannot
meet on a public repository, and which is long enough and large enough to hold the screen for
the 12-18 seconds one of these cards lasts. A hit that is 3 seconds of 480p is not coverage.

Sources, and what each needs:

  pexels    PEXELS_API_KEY   - free, instant, the licence is one blanket grant for the whole
                               library (no attribution required, commercial use allowed)
  pixabay   PIXABAY_API_KEY  - free, instant, Content Licence, same shape
  commons   none             - Wikimedia Commons, every file licensed individually, so the
                               licence of each hit is read and the restrictive ones dropped

Commons needs no key, so the keyless part of the number can always be produced. It is reported
separately rather than mixed in, because it is a floor and not the answer.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SUBJECTS = ROOT / "assets" / "subjects.json"
OUT = ROOT / "data" / "stock-coverage.json"
UA = "yt-kids/0.1 (coverage measurement; contact via the repository)"

# What a clip has to be before it counts. A card holds the screen for 12-18 seconds; a clip
# shorter than MIN_SECONDS cannot fill one without a loop so obvious a child sees it.
MIN_SECONDS = 8
MIN_WIDTH = 1280
# Pixabay's isLowQuality is not a quality signal: it is True on 1920x1080 clips with eleven
# thousand downloads, and refusing it threw away 17 of the 18 whale clips. Only isAiGenerated
# (this channel exists to show a real whale) and isGRated are believed. Portrait clips are
# refused instead, which isLowQuality was accidentally catching some of: a 1080x1920 clip in a
# 16:9 frame is two black bars and a letterbox.
LANDSCAPE_RATIO = 1.2

# Commons licences we may use on a monetised channel without a burden we cannot carry.
# CC0 and PD need no attribution; BY and BY-SA do, and the description can carry it, so they
# count - but SA infects nothing here because a video is not a derivative work of a clip in
# the sense that matters for the whole video. NC and ND are refused outright.
COMMONS_OK = ("cc0", "cc-zero", "public domain", "pd-", "cc-by-4.0", "cc-by-sa-4.0",
              "cc-by-3.0", "cc-by-sa-3.0", "cc-by-2.0", "cc-by-sa-2.0", "attribution")
COMMONS_NO = ("nc", "nd", "noncommercial", "no derivative", "fair use", "nonfree")


RETRIES = 5


def get_json(url, headers=None, timeout=30):
    """One request, retried on a throttle. Raises if it never gets an answer.

    It has to raise rather than return nothing, because the one thing this measurement must
    never do is report a request that failed as a subject that has no footage. The first run
    did exactly that: 50 of the 60 lookups came back HTTP 429 and the report called the result
    7% coverage. A rate limit is not a fact about whales.
    """
    last = None
    for attempt in range(1, RETRIES + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 503):
                raise
            wait = float(e.headers.get("Retry-After") or 0) or min(2 ** attempt, 30)
            print(f"    throttled ({e.code}), waiting {wait:.0f}s "
                  f"[{attempt}/{RETRIES}]", flush=True)
            time.sleep(wait)
    raise last


# --- the three sources -------------------------------------------------------------------

def pexels(term, key):
    """Pexels Licence: free for commercial use, no attribution required."""
    url = ("https://api.pexels.com/videos/search?per_page=5&orientation=landscape&query="
           + urllib.parse.quote(term))
    data = get_json(url, {"Authorization": key})
    for v in data.get("videos", []):
        big = [f for f in v.get("video_files", []) if (f.get("width") or 0) >= MIN_WIDTH]
        if big and (v.get("duration") or 0) >= MIN_SECONDS:
            return {"id": v["id"], "url": v["url"], "seconds": v["duration"],
                    "width": max(f["width"] for f in big), "licence": "Pexels Licence",
                    "attribution_required": False}
    return None


def _relevant(term, hit):
    """Whether the clip is actually OF the thing, not merely found by searching for it.

    Commons taught this first: searching "dolphin" returned satellite footage of Typhoon
    Dolphin, and "whale" an empty swimming pool, because a free-text search matches a file's
    title and description. Pixabay tags each clip with what is in it, which is better - but
    the search ORs the words, so a first version of this that accepted ANY word of the term
    let "school bus" through on a clip of a SCHOOL of fish, and "sea turtle" would have taken
    anything at sea.

    So the head noun has to be there: the last word of the term, which in English is the
    thing itself and not what kind of thing it is - bus, turtle, truck, car. A singular that
    only appears as a plural counts, and the other way round.
    """
    tags = {t.strip().lower() for t in (hit.get("tags") or "").split(",")}
    words = {w for tag in tags for w in tag.split()}
    head = term.lower().split()[-1]
    forms = {head, head + "s", head.rstrip("s")}
    if head.endswith("y"):
        forms.add(head[:-1] + "ies")
    if head.endswith("ies"):
        forms.add(head[:-3] + "y")
    return bool(forms & (tags | words))


def pixabay(term, key):
    """Pixabay Content Licence: free for commercial use, no attribution required.

    Three of the flags Pixabay returns decide more here than the licence does:

    isAiGenerated  refused. The entire premise of this channel is that a real whale swimming
                   beats a drawing of one for a two-year-old. A generated clip is a drawing
                   with extra steps, and we have our own generator for the cards that need one.
    isGRated       required. A channel made for children cannot gamble on this.
    isLowQuality   refused. The uploader's own judgement, and it costs nothing to believe it.
    """
    url = ("https://pixabay.com/api/videos/?per_page=12&video_type=film&safesearch=true&q="
           + urllib.parse.quote(term) + "&key=" + key)
    data = get_json(url)
    for v in data.get("hits", []):
        if v.get("isAiGenerated") or v.get("isGRated") is False:
            continue
        if not _relevant(term, v):
            continue
        streams = [s for s in (v.get("videos") or {}).values()
                   if (s.get("width") or 0) >= MIN_WIDTH
                   and (s.get("width") or 0) >= (s.get("height") or 1) * LANDSCAPE_RATIO]
        if streams and (v.get("duration") or 0) >= MIN_SECONDS:
            best = max(streams, key=lambda s: s["width"])
            return {"id": v["id"], "url": v.get("pageURL"), "seconds": v["duration"],
                    "width": best["width"], "licence": "Pixabay Content Licence",
                    "attribution_required": False, "tags": v.get("tags"),
                    "thumbnail": best.get("thumbnail"),
                    "clip": (v.get("videos", {}).get("small")
                             or v.get("videos", {}).get("tiny") or {}).get("url")}
    return None


def commons(term):
    """Wikimedia Commons. Every file carries its own licence, so each hit is read."""
    search = urllib.parse.quote(f"{term} filetype:video")
    found = get_json("https://commons.wikimedia.org/w/api.php?action=query&list=search"
                     f"&srsearch={search}&srnamespace=6&srlimit=8&format=json")
    titles = [r["title"] for r in found.get("query", {}).get("search", [])]
    if not titles:
        return None
    meta = get_json("https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo"
                    "&iiprop=url|size|mediatype|extmetadata&format=json&titles="
                    + urllib.parse.quote("|".join(titles[:8])))
    for page in (meta.get("query", {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        extra = info.get("extmetadata") or {}
        licence = (extra.get("LicenseShortName", {}).get("value") or "").strip()
        low = licence.lower()
        duration = float(info.get("duration") or 0)
        width = int(info.get("width") or 0)
        if any(bad in low for bad in COMMONS_NO):
            continue
        if not any(ok in low for ok in COMMONS_OK):
            continue
        if duration < MIN_SECONDS or width < MIN_WIDTH:
            continue
        return {"id": page.get("title"), "url": info.get("descriptionurl"),
                "seconds": round(duration), "width": width, "licence": licence,
                "attribution_required": "cc-by" in low.replace(" ", "-")
                or "attribution" in low}
    return None


SOURCES = {"pexels": ("PEXELS_API_KEY", pexels),
           "pixabay": ("PIXABAY_API_KEY", pixabay),
           "commons": (None, commons)}


def key_for(name):
    env, _ = SOURCES[name]
    if env is None:
        return None
    value = os.environ.get(env)
    if value:
        return value
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{env}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def measure(subjects, wanted, pause=0.4):
    results = {}
    for theme, items in subjects.items():
        for term in items:
            row = {}
            for name in wanted:
                env, fn = SOURCES[name]
                key = key_for(name)
                if env and not key:
                    continue
                try:
                    row[name] = fn(term, key) if env else fn(term)
                except urllib.error.HTTPError as e:
                    row[name] = {"error": f"HTTP {e.code}"}
                except Exception as e:                           # noqa: BLE001
                    row[name] = {"error": str(e)[:80]}
                time.sleep(pause)
            results[term] = {"theme": theme, **row}
            hit = [n for n, v in row.items() if v and "error" not in v]
            failed = [n for n, v in row.items() if v and "error" in v]
            if hit:
                note = "covered by " + ", ".join(hit)
            elif failed:
                note = "COULD NOT ASK (" + ", ".join(f"{n}: {row[n]['error']}" for n in failed) + ")"
            else:
                note = "nothing usable"
            print(f"  {term:14} {note}", flush=True)
    return results


def report(results, wanted):
    """The number, and - separately - how much of the measurement is missing.

    Coverage is a percentage of the subjects that were actually asked about. A subject whose
    lookup errored is in neither the numerator nor the denominator, and is named, so a
    half-finished run cannot be mistaken for a low score.
    """
    total = len(results)
    covered, missing, unknown = [], [], []
    for term, row in results.items():
        answers = {n: row.get(n) for n in wanted if n in row}
        if any(v and "error" not in v for v in answers.values()):
            covered.append(term)
        elif answers and all(v and "error" in v for v in answers.values()):
            unknown.append(term)
        else:
            missing.append(term)

    asked = total - len(unknown)
    lines = [f"{len(covered)} of {asked} subjects asked about are covered "
             f"({100 * len(covered) / asked:.0f}%)" if asked else "nothing could be measured"]
    for name in wanted:
        got = [t for t, r in results.items() if r.get(name) and "error" not in r[name]]
        could = [t for t, r in results.items() if r.get(name) is None
                 or (r.get(name) and "error" not in r[name])]
        if could:
            lines.append(f"  {name:9} {len(got):3} of {len(could)} "
                         f"({100 * len(got) / len(could):.0f}%)")
    if missing:
        lines.append(f"  not covered: {', '.join(sorted(missing))}")
    if unknown:
        lines.append(f"  COULD NOT ASK about {len(unknown)}, so they are in neither figure: "
                     f"{', '.join(sorted(unknown))}")
    return "\n".join(lines), len(unknown)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", choices=sorted(SOURCES),
                        help="repeatable; default is every source that has a key")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--pause", type=float, default=1.2,
                        help="seconds between requests; Commons throttles an anonymous "
                             "caller hard, and a throttled run is not a measurement")
    args = parser.parse_args(argv)

    subjects = json.loads(SUBJECTS.read_text(encoding="utf-8"))
    wanted = args.source or [n for n in SOURCES if key_for(n) or n == "commons"]
    skipped = [n for n in SOURCES if n not in wanted]
    print(f"measuring {sum(len(v) for v in subjects.values())} subjects against: "
          f"{', '.join(wanted)}")
    if skipped:
        print(f"skipped for want of a key: {', '.join(skipped)}")

    results = measure(subjects, wanted, pause=args.pause)
    text, unknown = report(results, wanted)
    print("\n" + text)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"min_seconds": MIN_SECONDS, "min_width": MIN_WIDTH,
                               "sources": wanted, "subjects": results}, indent=2),
                   encoding="utf-8")
    print(f"\nwritten to {out}")
    # A run that could not ask about some subjects exits non-zero: the number it printed is
    # about fewer subjects than the list holds, and nothing downstream should take it as final.
    return 1 if unknown else 0


if __name__ == "__main__":
    sys.exit(main())
