"""Stage 5: the title, the description and the tags.

The title follows the formula that wins in this niche, and it is built in code rather than
asked of a model, because the formula is the whole point and a model asked for a title every
day will drift off it:

    number + what + who it is for + the hook
    "25 Sea Animals for Kids | Learn Ocean Animals with Real Sounds"

The number is real - it is how many cards are in the video - and the hook names the thing this
channel has that the others do not, which is the real recorded sound after every name.

The description lists every card in order. That is not padding: it is what a parent scans to
decide whether the video is worth putting on, and it is the only place the sounds' attribution
can live for the few that are CC-BY rather than CC0.

YouTube's limits are checked here, not discovered at upload: 100 characters for a title and
5000 bytes for a description, and the tag field is 500 characters in total.
"""
import json
import re

from core.logger import get_logger

log = get_logger("seo")

MAX_TITLE = 100
MAX_DESCRIPTION_BYTES = 5000
MAX_TAGS_CHARS = 500

THEME_WORDS = {
    "farm animals": ("Farm Animals", "Learn Farm Animal Names and Sounds"),
    "wild animals": ("Wild Animals", "Learn Zoo and Safari Animals"),
    "sea animals": ("Sea Animals", "Learn Ocean Animals with Real Sounds"),
    "birds": ("Birds", "Learn Bird Names and Bird Songs"),
    "insects": ("Bugs and Insects", "Learn Insect Names for Toddlers"),
    "transport": ("Vehicles", "Learn Cars, Trucks and Machines"),
    "fruit and vegetables": ("Fruits and Vegetables", "Learn Healthy Food Names"),
    "animals": ("Animals", "Learn Animal Names and Real Animal Sounds"),
    "vehicles": ("Vehicles", "Learn Cars, Trucks and Machines"),
    "food": ("Fruits and Vegetables", "Learn Healthy Food Names"),
    "animals and machines": ("Animals and Vehicles", "Learn First Words with Real Sounds"),
}

BASE_TAGS = ["learning videos for toddlers", "toddler learning", "first words",
             "educational videos for kids", "preschool learning", "speech practice",
             "learn english for kids", "kids learning video", "real animal sounds",
             "toddler vocabulary"]


# Several shapes for a title, so a channel page is not one sentence repeated. Each still
# carries the number, the thing and who it is for; they differ in which comes first and what
# the hook is. The shape is picked by the video number, and then by what has not been used
# lately - three videos running called "30 Animals for Kids | Learn Animal Names and Real
# Animal Sounds" is what this exists to stop.
TITLE_SHAPES = [
    "{n} {what} for Kids | {hook}",
    "Learn {what} for Toddlers | {n} {things} with Real Sounds",
    "{n} {what} for Kids | Can You Name Them All?",
    "{what} for Kids | Learn {n} {things} and Their Sounds",
    "Guess the {one} Sound! | {n} {what} for Toddlers",
    "{n} {what} for Babies and Toddlers | First Words",
]

# The singular, for the shapes that need one ("Guess the Bird Sound!").
ONE_OF = {"animals": "Animal", "farm animals": "Farm Animal", "wild animals": "Wild Animal",
          "sea animals": "Sea Animal", "birds": "Bird", "insects": "Bug",
          "transport": "Vehicle", "vehicles": "Vehicle",
          "fruit and vegetables": "Food", "food": "Food"}


def title_options(theme, card_count, with_sounds):
    """Every title this video could have, best first."""
    key = (theme or "").lower()
    what, hook = THEME_WORDS.get(key, ((theme or "First Words").title(),
                                       "Learn First Words for Toddlers"))
    if not with_sounds:
        hook = hook.replace(" with Real Sounds", "").replace(" and Real Animal Sounds", "")
    one = ONE_OF.get(key, what.rstrip("s") or what)
    out = []
    for shape in TITLE_SHAPES:
        if "{hook}" in shape and not hook:
            continue
        if ("Sound" in shape) and not with_sounds:
            continue
        title = shape.format(n=card_count, what=what, hook=hook, things=what, one=one)
        if len(title) <= MAX_TITLE and title not in out:
            out.append(title)
    if not out:
        out = [f"{card_count} {what} for Kids"]
    return out


def title_for(theme, card_count, with_sounds, video_id=0, recent_titles=()):
    """A title that none of the recent videos used.

    The shape rotates with the video number so neighbours differ even on the same theme, and
    anything a recent video was actually called is skipped - checked against the database
    rather than assumed, because the rotation alone cannot know a video failed and was remade.
    """
    options = title_options(theme, card_count, with_sounds)
    taken = {t.strip().lower() for t in recent_titles if t}
    start = int(video_id) % len(options)
    ordered = options[start:] + options[:start]
    for title in ordered:
        if title.strip().lower() not in taken:
            return title
    # Every shape is spoken for. Say so in the title rather than repeat one silently: the
    # count makes it true and different.
    return ordered[0]


# --- since the move to the new channel: titles from real searches ---------------------------
#
# The owner's rule: each title is built on a search people really type, from YouTube's own
# autocomplete (core/suggest.py), and no two videos of the channel share a title or a search.
# The search leads; the part after the bar says what is in the video and rotates, so even two
# themes found by the same kind of search do not read alike.

TAILS = ["{n} {name} with Real Sounds",
         "Learn {n} {name} and Play Guess Who",
         "Name {n} {name} and Guess Them All",
         "{n} Real {name} for Little Learners"]
QUIET_TAILS = ["Learn {n} {name} and Play Guess Who",
               "Name {n} {name} and Guess Them All",
               "{n} Real {name} for Little Learners"]


def catalogue_title(theme, card_count, with_sounds, video_id, taken_titles, taken_queries,
                    opener=None):
    """(title, query) for a catalogue theme, or (None, None) if no usable search was found."""
    from core import suggest
    taken_titles = {t.strip().lower() for t in taken_titles if t}
    taken_queries = {q.strip().lower() for q in taken_queries if q}
    queries = [q for q in suggest.candidates(theme, opener) if q not in taken_queries]
    # The search that names the most of the theme first ("fruits and vegetables for kids"
    # for fruits AND vegetables, not "fruits for toddlers"); then the audience the channel is
    # for, toddlers before babies; then the plainest, fewer words being what more people typed.
    name_words = {w for w in theme["name"].lower().split() if len(w) > 3}
    audience = ["toddlers", "toddler", "kids", "preschool", "preschoolers", "kindergarten",
                "children", "babies", "baby"]

    def rank(q):
        words = q.split()
        named = sum(1 for w in name_words if w in words)
        heard = min([audience.index(w) for w in words if w in audience] or [len(audience)])
        return (-named, heard, len(words), q)
    queries.sort(key=rank)
    tails = TAILS if with_sounds else QUIET_TAILS
    start = int(video_id) % len(tails)
    for query in queries:
        lead = suggest.title_case(query)
        for tail in tails[start:] + tails[:start]:
            title = f"{lead} | {tail.format(n=card_count, name=theme['name'])}"
            if len(title) <= MAX_TITLE and title.lower() not in taken_titles:
                return title, query
    return None, None


DESCRIPTION_OPENINGS = [
    "{blurb} {n} {name_lower} for toddlers and preschoolers, shown in real video, named "
    "slowly, and then played as a guessing game.",
    "{n} {name_lower}, one at a time: a real clip, the name said clearly, {sound_part}and one "
    "small thing to remember. {blurb}",
    "Made for children aged 2 to 6. {blurb} After all {n} have been met, the guessing game "
    "begins: a piece of the picture, a countdown, and the answer.",
]


def catalogue_description(theme, cards, attributions, variant, query):
    """The description for a catalogue theme. The opening rotates with the channel's video
    count and the theme's own line and search lead it, so no two read alike."""
    n = len(cards)
    sounded = sum(1 for c in cards if c.get("sound_id"))
    opening = DESCRIPTION_OPENINGS[variant % len(DESCRIPTION_OPENINGS)].format(
        blurb=theme.get("blurb", ""), n=n, name_lower=theme["name"].lower(),
        sound_part="the real sound it makes, " if sounded else "")
    parts = [opening.strip(), "", f"In this video ({query}):",
             "\n".join(f"- {c['subject'].title()}" for c in cards), "",
             "Pause after each name so your child can say it back. Best watched together."]
    if sounded:
        parts += ["", f"{sounded} of the {n} have a real recorded sound."]
    if attributions:
        parts += ["", "Sounds used under Creative Commons Attribution:"]
        parts += [f"- {line}" for line in attributions]
    parts += ["", "This channel is made for children. Comments are turned off, which is what "
                  "YouTube requires of videos made for kids."]
    return "\n".join(parts)


def description_for(theme, cards, attributions):
    """What is in the video, in order, and where the sounds came from."""
    what, _hook = THEME_WORDS.get(theme.lower(), (theme.title(), ""))
    listed = "\n".join(f"- {c['subject'].title()}" for c in cards)
    sounded = sum(1 for c in cards if c.get("sound_id"))

    parts = [
        f"Learn {len(cards)} {what.lower()} with real pictures and real sounds. "
        f"Made for toddlers and preschoolers aged 2 to 6.",
        "",
        "Each one is shown, named slowly, and then there is a pause so your child can say "
        "the word back. After the name comes the real sound it makes, and one short thing "
        "about it that a small child can picture.",
        "",
        f"In this video:",
        listed,
        "",
        "Best watched together, so you can say the words with them.",
    ]
    if sounded:
        parts += ["", f"{sounded} of the {len(cards)} have a real recorded sound."]
    if attributions:
        parts += ["", "Sounds used under Creative Commons Attribution:"]
        parts += [f"- {line}" for line in attributions]
    parts += ["", "This channel is made for children. Comments are turned off, which is what "
                  "YouTube requires of videos made for kids."]
    return "\n".join(parts)


def tags_for(theme, cards):
    what, _ = THEME_WORDS.get(theme.lower(), (theme.title(), ""))
    tags = [what.lower(), f"{what.lower()} for kids", *BASE_TAGS]
    tags += [c["subject"].lower() for c in cards[:8]]
    out, used = [], 0
    for tag in tags:
        if tag in out:
            continue
        if used + len(tag) + 1 > MAX_TAGS_CHARS:
            break
        out.append(tag)
        used += len(tag) + 1
    return out


def run(video_id, cfg, db, output_dir=None):
    video = db.get_video(video_id) or {}
    cards = db.get_cards(video_id)
    if not cards:
        raise RuntimeError("there are no cards to describe")
    theme = video.get("theme") or "animals and machines"
    with_sounds = any(c.get("sound_id") for c in cards)
    attributions = [c["sound_attribution"] for c in cards
                    if c.get("sound_attribution")]

    from pipeline import plan as _plan
    entry = _plan.theme_by_id(video.get("theme_id")) if video.get("theme_id") else None
    query = None
    if entry is not None:
        # Every other video of the channel, ever - not just the recent ones: a title or a
        # search used once is used up. Not this video's own: a rerun must not avoid itself.
        others = [v for v in db.channel_videos() if v["id"] != video_id]
        title, query = catalogue_title(entry, len(cards), with_sounds, video_id,
                                       [v.get("seo_title") for v in others],
                                       [v.get("title_query") for v in others])
        if title is None:
            raise RuntimeError(f"no YouTube search for theme {entry['id']} is left unused; "
                               f"add seeds to assets/themes.json rather than repeat a title")
        description = catalogue_description(entry, cards, attributions, len(others), query)
        tags = tags_for(theme, cards)
        tags = [query] + [t for t in tags if t != query]
    else:
        # Not this video's own earlier title: a rerun must not avoid itself.
        recent = [v.get("seo_title") for v in db.recent_videos(11) if v["id"] != video_id]
        title = title_for(theme, len(cards), with_sounds, video_id, recent)
        if title.strip().lower() in {t.strip().lower() for t in recent if t}:
            log.warning("this title has been used by a recent video and no other shape was "
                        "free: %r", title)
        description = description_for(theme, cards, attributions)
        tags = tags_for(theme, cards)

    if len(title) > MAX_TITLE:
        raise RuntimeError(f"title is {len(title)} characters, YouTube allows {MAX_TITLE}")
    if len(description.encode("utf-8")) > MAX_DESCRIPTION_BYTES:
        description = description.encode("utf-8")[:MAX_DESCRIPTION_BYTES - 3].decode(
            "utf-8", "ignore") + "..."

    db.update_video(video_id, seo_title=title, description=description,
                    tags=json.dumps(tags, ensure_ascii=False),
                    **({"title_query": query} if query else {}))
    log.info("title (%d chars): %s", len(title), title)
    log.info("%d tags, description %d bytes, %d sound attribution(s)",
             len(tags), len(description.encode("utf-8")), len(attributions))
    db.log_event(video_id, "seo", "info",
                 f"{len(title)} char title, {len(tags)} tags, "
                 f"{len(attributions)} attributions")
    return True
