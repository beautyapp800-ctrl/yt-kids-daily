"""The sound a thing makes, which for a two-year-old is the strongest part of the card.

Openverse aggregates Freesound and others, needs no key, and returns the licence of every
result, which is what makes it usable in a public repository at all.

What is refused, and why:

  nc  the channel is monetised, so non-commercial is out.
  nd  no derivatives, and trimming a clip to four seconds and mixing it under a voice is
      exactly a derivative.
  sa  share-alike would put the whole finished video under the same licence. One four-second
      quack is not worth that, and there are thousands of cc0 quacks.

So only CC0, public domain and plain CC-BY are kept, and BY carries attribution into the
description.

The harder problem is that a sound cannot be verified the way a picture can. There is no free
classifier that will say "this is a cow". The title is all there is, and titles lie: searching
"lion roar" returns "Zombie (Or Monster Or Lion) Roar", which is a monster. So the subject has
to be in the title, and a list of words that give away a sound that is not the real animal -
toy, synth, imitation, remix - rejects it. That is a weaker net than the one over the pictures
and it is written down here as such: a wrong sound on a learning video teaches a child the
wrong thing, so anything this cannot vouch for is left silent rather than guessed at.
"""
import json
import re
import urllib.parse
import urllib.request

from core.logger import get_logger

log = get_logger("sounds")

API = "https://api.openverse.org/v1/audio/"
UA = "yt-kids/0.1 (educational videos for children; contact via the repository)"

ALLOWED = {"cc0", "pdm", "by"}
REFUSED_REASON = {"by-sa": "share-alike would put the whole video under it",
                  "by-nc": "the channel is monetised", "by-nc-sa": "both of the above",
                  "by-nc-nd": "both of the above", "by-nd": "a trim is a derivative",
                  "nc-sampling+": "non-commercial", "sampling+": "unclear for this use"}

# Words that mean the sound is not the real thing, however well the title matches.
NOT_THE_REAL_THING = {"toy", "synth", "synthesized", "synthesised", "imitation", "imitating",
                      "fake", "remix", "cover", "song", "music", "melody", "ringtone", "meme",
                      "zombie", "monster", "dragon", "cartoon", "voice", "human", "man",
                      "woman", "scream", "8-bit", "chiptune", "sample pack"}

MIN_SECONDS = 1.0
MAX_SECONDS = 30.0


class SoundError(Exception):
    pass


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.load(resp)


def usable_licence(licence):
    return (licence or "").lower() in ALLOWED


def title_is_honest(subject, title):
    """The subject is named and nothing in the title says it is an imitation of one."""
    words = set(re.findall(r"[a-z0-9+']+", (title or "").lower()))
    head = subject.lower().split()[-1]
    if not ({head, head + "s", head.rstrip("s")} & words):
        return False
    return not (words & NOT_THE_REAL_THING)


def search(subject, query=None, page_size=20):
    """[(record)] of sounds that may be used for this subject, best licence first."""
    q = query or subject
    data = _get(API + "?page_size=" + str(page_size) + "&q=" + urllib.parse.quote(q))
    out = []
    for r in data.get("results", []):
        licence = (r.get("license") or "").lower()
        seconds = (r.get("duration") or 0) / 1000
        if not usable_licence(licence):
            continue
        if not MIN_SECONDS <= seconds <= MAX_SECONDS:
            continue
        if not title_is_honest(subject, r.get("title")):
            continue
        out.append({
            "id": r.get("id"), "title": r.get("title"), "seconds": round(seconds, 1),
            "licence": licence, "licence_version": r.get("license_version"),
            "licence_url": r.get("license_url"), "source": r.get("source"),
            "creator": r.get("creator"), "page": r.get("foreign_landing_url"),
            "url": r.get("url"),
            "attribution_required": licence == "by",
        })
    # CC0 first: no attribution to carry, and nothing to get wrong later.
    out.sort(key=lambda s: (s["licence"] != "cc0", s["licence"] != "pdm"))
    return out


def attribution_line(sound):
    """The line that goes in the description for a sound that needs one."""
    if not sound.get("attribution_required"):
        return ""
    return (f"{sound.get('title')} by {sound.get('creator') or 'unknown'} "
            f"({sound.get('page')}), licensed CC BY "
            f"{sound.get('licence_version') or ''}".strip())
