"""Find the game's sound effects: CC0 only, licence read at the source, then measured.

    python scripts/find_sfx.py            # search, verify, download, measure; print a table
    python scripts/find_sfx.py --keep     # and copy the chosen ones into assets/sfx/

Four effects: a pop and a whoosh for the reveal, a tick for the countdown, a short cheerful
sting for the "Guess who?" card. Each is searched on Openverse, but the licence is read from
the page that hosts the file (core/licence.py) - Openverse once called a CC BY-NC track CC0.

Every candidate that survives is measured rather than trusted by its title: how long the sound
itself is once silence is trimmed off both ends, and how quickly it reaches its peak (a pop
that takes half a second to arrive is not a pop). Every verified candidate is written to
data/sfx-candidates/candidates.json, so the choice can be checked by someone else.

The title is read as well, because a waveform does not say whether a jingle is cheerful. The
first pass chose by length alone and picked "sword battle jingle loop", with "You failed (game
jingle)" right behind it - the right length, and the wrong thing to play to a three-year-old
before a game.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import licence
from core.sounds import API, _get

WORK = ROOT / "data" / "sfx-candidates"
OUT = ROOT / "assets" / "sfx"
UA = "yt-kids/0.1 (sound effects)"

# name: (queries, how quickly it must reach its peak, in seconds)
NEEDS = {
    "pop":    (["pop", "bubble pop", "cork pop", "pop sound effect"], 0.08),
    "whoosh": (["whoosh", "swoosh", "swish"], 0.9),
    "tick":   (["clock tick", "tick", "tick tock"], 0.05),
    "sting":  (["happy jingle", "success jingle", "achievement jingle", "fanfare", "ta da",
                "game start jingle", "level complete", "positive jingle"], 2.0),
}
# How long the sound itself may be once silence is trimmed off both ends.
ACTIVE = {"pop": (0.06, 0.6), "whoosh": (0.2, 1.3), "tick": (0.015, 0.3), "sting": (0.8, 3.6)}

NEGATIVE = {"fail", "failed", "failure", "lose", "lost", "loser", "over", "sad", "battle",
            "sword", "mystery", "horror", "scary", "creepy", "error", "wrong", "dark", "evil",
            "alarm", "gun", "shot", "explosion", "death", "die", "dead", "angry", "monster",
            "keys", "voice", "speech", "word", "ll", "loop"}
POSITIVE = {"happy", "success", "achievement", "ready", "start", "win", "winner", "positive",
            "cheerful", "fanfare", "tada", "level", "bonus", "correct", "reward", "magic",
            "fun", "kids", "cute", "complete", "victory", "yay", "bright"}


def search(query, pages=2):
    """Openverse answers an anonymous request with at most 20 results, so two pages."""
    out = []
    for page in range(1, pages + 1):
        try:
            data = _get(API + f"?page_size=20&page={page}&license=cc0&q=" +
                        urllib.parse.quote(query))
        except Exception:                                        # noqa: BLE001
            break
        out += data.get("results", [])
        if len(data.get("results", [])) < 20:
            break
    return out


def fetch(url, dst):
    if dst.exists() and dst.stat().st_size > 500:
        return dst
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        dst.write_bytes(r.read(8 * 1024 * 1024))
    return dst


def trim(src, dst, floor_db=-45):
    """The sound with silence cut from both ends - the measurement and the kept file use this."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af",
                    f"silenceremove=start_periods=1:start_threshold={floor_db}dB,"
                    f"areverse,silenceremove=start_periods=1:start_threshold={floor_db}dB,"
                    "areverse", "-ac", "2", "-ar", "44100", str(dst)],
                   check=True, capture_output=True, timeout=120)
    return dst


def words(title):
    return set(re.findall(r"[a-z]+", (title or "").lower()))


def measure(path):
    """{seconds, attack} from the trimmed file itself."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "22050",
                          "-f", "s16le", "-"], capture_output=True, timeout=120).stdout
    a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if len(a) < 200:
        return None
    env = np.abs(a)
    return {"seconds": round(len(a) / 22050, 3),
            "attack": round(int(np.argmax(env)) / 22050, 3)}


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)
    WORK.mkdir(parents=True, exist_ok=True)

    chosen, candidates = {}, []
    for name, (queries, max_attack) in NEEDS.items():
        seen, rows = set(), []
        lo, hi = ACTIVE[name]
        for q in queries:
            for r in search(q):
                if r.get("id") in seen:
                    continue
                seen.add(r.get("id"))
                if (r.get("duration") or 0) / 1000 <= hi + 4.0:
                    rows.append(r)
        print(f"\n== {name}: {len(rows)} CC0-labelled candidates")
        good = []
        for r in rows[:24]:
            title = r.get("title") or ""
            if words(title) & NEGATIVE:
                print(f"   refused by title: {title[:50]}")
                continue
            found, evidence = licence.verify({"page": r.get("foreign_landing_url"),
                                              "source": r.get("source")})
            if not licence.usable(found):
                print(f"   refused at source ({found}): {title[:40]}")
                continue
            ext = Path(urllib.parse.urlparse(r.get("url") or "").path).suffix or ".mp3"
            raw = WORK / f"{name}_{r['id']}{ext}"
            try:
                fetch(r["url"], raw)
                trimmed = trim(raw, WORK / f"{name}_{r['id']}_trim.wav")
                m = measure(trimmed)
            except Exception as e:                               # noqa: BLE001
                print(f"   could not fetch or read: {str(e)[:60]}")
                continue
            if not m:
                continue
            ok = lo <= m["seconds"] <= hi and m["attack"] <= max_attack
            liked = len(words(title) & POSITIVE)
            print(f"   {'ok ' if ok else '-- '} {m['seconds']:5.3f}s attack {m['attack']:.3f}s "
                  f"+{liked}  {title[:46]}  [{found}]")
            row = {"need": name, "title": title, "page": r.get("foreign_landing_url"),
                   "creator": r.get("creator"), "licence": found, "evidence": evidence,
                   "measured": m, "ok": ok, "positive_words": liked, "file": str(trimmed)}
            candidates.append(row)
            if ok:
                good.append(row)
        if not good:
            print(f"   NOTHING usable for {name}")
            continue
        if name == "sting":
            # A positive title first, then nearest two seconds.
            key = lambda g: (-g["positive_words"], abs(g["measured"]["seconds"] - 2.0))  # noqa
        else:
            # The one whose own name says what it is, then the quickest to its peak.
            key = lambda g: (name not in words(g["title"]), g["measured"]["attack"])    # noqa
        best = sorted(good, key=key)[0]
        chosen[name] = {"file": f"{name}.wav", "title": best["title"],
                        "creator": best["creator"], "page": best["page"], "licence": "cc0",
                        "licence_checked_at_source": True, "evidence": best["evidence"],
                        "measured": best["measured"], "candidate": best["file"]}
        print(f"   CHOSEN: {best['title']}  ({best['measured']['seconds']}s)")

    (WORK / "candidates.json").write_text(json.dumps(candidates, indent=1), encoding="utf-8")
    print("\nchosen:")
    for name, row in chosen.items():
        print(f"  {name:7} {row['title'][:50]:50} {row['measured']['seconds']:.3f}s  {row['page']}")
    if args.keep and chosen:
        OUT.mkdir(parents=True, exist_ok=True)
        for name, row in chosen.items():
            shutil.copy(row.pop("candidate"), OUT / row["file"])
        (OUT / "licences.json").write_text(json.dumps(chosen, indent=2), encoding="utf-8")
        print(f"kept {len(chosen)} in {OUT}")
    return 0 if len(chosen) == len(NEEDS) else 1


if __name__ == "__main__":
    sys.exit(main())
