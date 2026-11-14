"""What people actually type into YouTube's search box, for the titles.

The owner's rule since the move to the new channel: a title is built on a real search, taken
from YouTube's own autocomplete, and no two videos of the channel share one. Autocomplete is
the public endpoint the search box itself calls (suggestqueries.google.com, ds=yt); it needs
no key and costs no quota. If it cannot be reached, the suggestions saved in
assets/themes.json the last time it could are used instead, so a network hiccup does not stop
a video.

Not every suggestion is a title for a toddlers' channel. "farm animals for dogs", "... toys",
"... spanish" and "... song" all come back for "farm animals for", and each one would promise
something the video is not, so a suggestion has to name the theme, name who it is for, and
carry none of the words that make it about something else.
"""
import json
import re
import urllib.parse
import urllib.request

from core.logger import get_logger

log = get_logger("suggest")

ENDPOINT = ("https://suggestqueries.google.com/complete/search?client=firefox&ds=yt"
            "&hl=en&gl=us&q={q}")
TIMEOUT_S = 15

AUDIENCE = ("kids", "kid", "toddlers", "toddler", "babies", "baby", "preschool",
            "preschoolers", "kindergarten", "children", "child")
# Words that would make the title promise a different video.
OFF_TOPIC = {"song", "songs", "toy", "toys", "spanish", "french", "hindi", "dogs", "cats",
             "minecraft", "roblox", "cartoon", "cartoons", "coloring", "colouring", "drawing",
             "draw", "craft", "crafts", "asmr", "scary", "horror", "funny", "prank", "game",
             "games", "puzzle", "worksheet", "book", "books", "story", "stories", "lyrics",
             "nursery", "rhymes", "rhyme", "dance", "sing", "glamour", "faded", "can't",
             "cannot", "costume", "pictures", "clipart", "png", "lego", "playdoh",
             # Caught in the first pull of suggestions, 14 November 2026: real searches, but
             # for a lunchbox, a remote-control toy, a pet shop or a bedtime video.
             "lunch", "lunches", "snack", "snacks", "recipe", "recipes", "rc", "best", "easy",
             "cheap", "small", "buy", "care", "together", "sleep", "bedtime", "uk", "ideas",
             "activities", "activity", "art", "printable", "costumes", "sensory", "fox",
             "videos", "video", "cows", "robot", "ferret", "ferrets", "national",
             "geographic", "cool", "cute", "good", "are", "is", "what", "how", "why", "which",
             "where", "who", "adaptations", "adaptation", "facts", "fact"}
MAX_WORDS = 6                    # a search, not a sentence


def fetch(query, opener=None):
    """Autocomplete suggestions for `query`, or [] if it could not be asked."""
    url = ENDPOINT.format(q=urllib.parse.quote(query))
    try:
        with (opener or urllib.request.urlopen)(url, timeout=TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
        return [str(s) for s in (data[1] if len(data) > 1 else [])]
    except Exception as e:                                       # noqa: BLE001
        log.warning("autocomplete for %r could not be fetched: %s", query, e)
        return []


def usable(query, keywords):
    """True if `query` names the theme, names who it is for, and is about nothing else."""
    words = re.findall(r"[a-z']+", query.lower())
    if not words or not re.fullmatch(r"[a-z0-9' ]+", query.lower().strip()):
        return False
    if OFF_TOPIC & set(words) or len(words) > MAX_WORDS:
        return False
    if not any(w in AUDIENCE for w in words):
        return False
    text = " " + " ".join(words) + " "
    return any(f" {k.lower()}" in text for k in keywords)


def candidates(theme, opener=None):
    """Usable searches for this theme, live ones first, then the saved ones; no duplicates."""
    seen, out = set(), []
    live = []
    for seed in theme.get("seeds", []):
        live += fetch(seed, opener)
        # The seed itself is a real search too when autocomplete offers it back.
    for q in live + list(theme.get("suggestions", [])):
        key = q.strip().lower()
        if key and key not in seen and usable(key, theme.get("keywords") or [theme["name"]]):
            seen.add(key)
            out.append(key)
    return out


def title_case(query):
    small = {"for", "and", "the", "of", "in", "on", "to", "a", "an", "with"}
    words = query.split()
    return " ".join(w if (i and w in small) else w[:1].upper() + w[1:]
                    for i, w in enumerate(words))
