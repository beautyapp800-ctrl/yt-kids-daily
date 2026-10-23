"""Stage 1: decide what the video is, and fill in every card before anything is spent.

Everything that can fail cheaply happens here, in this order: pick a theme, pick its subjects,
write the facts, find a clip for each, find a sound for each. Nothing is downloaded, drawn or
spoken until the whole plan stands, because a plan that falls apart on card nineteen has
already paid for eighteen pictures.

Two rules shape the choice of subjects:

- a clip is used once per video, which is why pick_clips is given the whole list at once and
  not asked subject by subject. The rooster case: one frame honestly answers both "chicken"
  and "rooster", and the child sees the same picture twice;
- subjects from the last few videos are avoided, so a weekly viewer is not shown the same
  lion every Tuesday. If avoiding them would leave too few, they come back - a short video is
  worse than a repeated lion.
"""
import random
from pathlib import Path

from core import db, soundcheck
from core.logger import get_logger
from pipeline import catalogue

log = get_logger("plan")

# Themes whose subjects make a sound. The brief asks for the real sound of the thing "where
# it has one: animals, transport" - and the search will always find SOMETHING, so without this
# a carrot card got "Eating a Carrot" and a tomato got "Tomato Squish". Those are sounds of a
# person eating, not of the thing, and they teach a child nothing.
SOUNDED_THEMES = {"farm animals", "wild animals", "sea animals", "birds", "insects",
                  "transport"}

MIN_CARDS = 18          # below this a full-length video is too short to be worth publishing
SUBJECT_POOL = 3.0      # how many candidates to consider per card wanted


# A video is one theme. It used to be a family - every kind of animal together - and three
# videos running came out called "30 Animals for Kids", sharing twenty subjects out of thirty.
# From a viewer's seat that is the same video three times; from YouTube's, it is repetition.
#
# One theme per video also spaces the subjects out on its own, with no extra rule: with seven
# themes in rotation a theme comes round every seventh video, so nothing inside it can return
# sooner than that. The arithmetic the family approach could never satisfy - thirty cards and
# no repeat within five videos needs 150 distinct subjects, and the animals family has 52.

THEME_REST = 7           # a theme comes back no sooner than the 7th video: once a week
SUBJECT_REST = 5         # videos a subject sits out, as asked
MIN_THEME_CARDS = 15     # every video takes exactly this many; a smaller theme waits


def theme_sizes(groups, clips, facts):
    """{theme: how many of its subjects could actually be a card today}."""
    return {theme: sum(1 for s in items
                       if (clips.get(s) or {}).get("clips") and (facts.get(s) or {}).get("facts"))
            for theme, items in groups.items()}


class NoThemeReady(RuntimeError):
    """No theme can make today's video under the rules. Not a fault to retry: a decision."""


def choose_theme(groups, recent, sizes, floor=MIN_THEME_CARDS, rest=THEME_REST):
    """The theme for this video: one that can fill it and has rested a week.

    Both are hard rules. A theme with fewer than `floor` subjects is not padded from another
    theme - padding is what produced four videos called "30 Animals for Kids" - and a theme used
    in the last `rest` videos does not come back early, because a theme twice in a week is the
    same video twice in a week. When nothing qualifies there is no video, and the reason names
    every theme's count and when it was last used, so whoever reads it can decide.
    """
    # Once a week means a theme used seven videos ago is free today, so it is the six before
    # this one that rule it out. Excluding seven would need eight themes to keep a daily rhythm.
    used = [v.get("theme") for v in recent[:rest - 1]]
    ago = {}
    for distance, name in enumerate(used):
        ago.setdefault(name, distance + 1)
    ready = [t for t, n in sizes.items() if n >= floor and t not in ago]
    if not ready:
        lines = []
        for t, n in sorted(sizes.items(), key=lambda kv: -kv[1]):
            why = []
            if n < floor:
                why.append(f"{n} of {floor} subjects")
            if t in ago:
                why.append(f"used {ago[t]} video(s) ago")
            lines.append(f"{t}: " + ("; ".join(why) or "ready"))
        raise NoThemeReady("no theme is ready for today's video - " + " | ".join(lines))
    # Never used, or used longest ago, first; then the fullest; then by name for a stable rerun.
    unseen = rest + 1
    return sorted(ready, key=lambda t: (-ago.get(t, unseen), -sizes[t], t))[0]


def choose_subjects(groups, theme, wanted, distances, rng, rest=SUBJECT_REST):
    """Subjects of `theme` for this video, the ones that have rested longest first.

    A subject used within the last `rest` videos is held back. If holding them all back leaves
    too few, the ones held back come in by distance - the one used longest ago first - because
    a short video is a worse answer than a lion a child saw four videos ago.
    """
    pool = list(groups.get(theme, []))
    rng.shuffle(pool)
    fresh = [s for s in pool if distances.get(s, rest + 1) > rest]
    chosen = fresh[:wanted]
    if len(chosen) < wanted:
        held = sorted((s for s in pool if s not in chosen),
                      key=lambda s: -distances.get(s, rest + 1))
        short = wanted - len(chosen)
        chosen += held[:short]
        log.info("theme %r could only offer %d subjects rested %d videos; %d came back early",
                 theme, len(fresh), rest, min(short, len(held)))
    return chosen


def theme_of(subject, groups):
    for name, items in groups.items():
        if subject in items:
            return name
    return ""


def dominant_theme(subjects, groups, fallback):
    """What the video is actually about, for the title: the theme most of its cards belong to.

    Kept even though a video is now planned as one theme, because the title must describe the
    cards that were made and not the intention behind them.
    """
    counted = {}
    for s in subjects:
        name = theme_of(s, groups)
        if name:
            counted[name] = counted.get(name, 0) + 1
    if not counted:
        return fallback
    best = max(counted.items(), key=lambda kv: (kv[1], kv[0]))
    return best[0] if best[1] >= len(subjects) * 0.7 else fallback


def run(video_id, cfg, account, token, groups, clips=None, sounds_module=None,
        rng=None, facts=None, sound_book=None):
    """Write the whole plan into the database. Returns True, or raises with a reason."""
    rng = rng or random.Random(int(video_id) * 7919)
    clips = clips if clips is not None else catalogue.load()
    fact_book = facts if facts is not None else _load_facts()
    sound_book = sound_book if sound_book is not None else _load_sounds()
    wanted = int(cfg.get("cards_per_video", 25))
    # The floor is relative: a configuration asking for eight cards means eight, and should
    # not be refused by a constant written for the full-length format.
    floor = min(MIN_CARDS, wanted)

    recent = db.recent_videos(max(THEME_REST, SUBJECT_REST) + 1)
    sizes = theme_sizes(groups, clips, fact_book)
    floor_cards = int(cfg.get("min_theme_cards", MIN_THEME_CARDS))
    theme = cfg.get("theme") or choose_theme(groups, recent, sizes, floor_cards)
    # Exactly this many, every video, so every video is the same length. A theme that has more
    # contributes a different fifteen each time it comes round; one that has fewer never got
    # here.
    wanted = min(wanted, sizes[theme])
    floor = wanted
    distances = db.subjects_used_in_last(SUBJECT_REST)
    subjects = choose_subjects(groups, theme, int(wanted * SUBJECT_POOL), distances, rng)
    log.info("video %s: theme %r (%d subjects ready, last %d videos were %s), asking for %d cards",
             video_id, theme, sizes[theme], len(recent),
             ", ".join(v.get("theme") or "?" for v in recent[:THEME_REST]) or "none", wanted)

    # The clip comes before the fact: a subject with no clip and no drawing is no card, and
    # writing a fact for it would be work thrown away.
    with_clip = catalogue.pick_clips(subjects, clips)
    usable = [(s, c) for s, c in with_clip if c is not None][:wanted]
    drawn = []
    if len(usable) < wanted:
        # Subjects the catalogue cannot film get drawn instead, which is what the picture
        # style is for. Taken in order, so the choice is the same on a rerun.
        for s, c in with_clip:
            if c is None and (s, None) not in usable and len(usable) + len(drawn) < wanted:
                drawn.append(s)
    plan = usable + [(s, None) for s in drawn]
    if len(plan) < floor:
        raise RuntimeError(f"only {len(plan)} cards could be planned for theme {theme!r}, "
                           f"and a video needs at least {floor}")

    # Facts come from assets/facts.json, checked once when they were added. The daily run
    # does not write a fact: three of the first forty the model wrote were false, and every
    # one passed the structural rules, so the check belongs where a rejection costs a retry
    # rather than a published video. A subject with no checked fact is simply not used.
    facts, missing = {}, []
    for subject, _clip in plan:
        choices = (fact_book.get(subject) or {}).get("facts") or []
        if choices:
            facts[subject] = choices[rng.randrange(len(choices))]["fact"]
        else:
            missing.append(subject)
    plan = [(s, c) for s, c in plan if s in facts]
    if len(plan) < floor:
        raise RuntimeError(f"only {len(plan)} cards had a checked fact (no fact for: "
                           f"{', '.join(missing)}), and a video needs {floor}. "
                           f"Run scripts/build_facts.py")

    sounds_module = sounds_module or _default_sounds()
    silent = []
    for idx, (subject, clip) in enumerate(plan):
        # From the catalogue, checked once when it was added. The daily run asks no model
        # about sounds at all: judging three or four candidates for twenty-five cards is a
        # hundred model calls a day for an answer that never changes, and it was what
        # exhausted the 10,000-neuron allowance mid-run.
        sound = None
        entry = sound_book.get(subject) or {}
        choices = entry.get("sounds") or []
        if choices:
            sound = choices[rng.randrange(len(choices))]
        if sound is None:
            silent.append(subject)
        db.add_card(
            video_id, idx, subject, fact=facts[subject],
            clip_id=str(clip["id"]) if clip else None,
            clip_url=(clip or {}).get("clip"),
            clip_licence=(clip or {}).get("licence"),
            video_source="stock" if clip else "drawn",
            sound_id=(sound or {}).get("id"),
            sound_licence=(sound or {}).get("licence"),
            sound_url=(sound or {}).get("url"),
            sound_attribution=sounds_module.attribution_line(sound) if sound else None)

    # The game shows every subject a second time. A clip is used in a video once - the rule
    # that came from the rooster - so the game takes a different clip of the same subject
    # where the catalogue has one, and the same clip only where it has no other.
    used = {str(c["id"]) for _s, c in plan if c}
    for card in db.get_cards(video_id):
        options = (clips.get(card["subject"]) or {}).get("clips") or []
        other = next((c for c in options if str(c["id"]) not in used), None)
        if other:
            used.add(str(other["id"]))
            db.update_card(card["id"], game_clip_id=str(other["id"]),
                           game_clip_url=other.get("clip"))

    db.remember_subjects(video_id, [s for s, _ in plan])
    shown = dominant_theme([s for s, _ in plan], groups, theme)
    db.update_video(video_id, theme=shown,
                    title=f"{len(plan)} {shown.title()} for Kids")
    log.info("planned %d cards: %d filmed, %d drawn, %d without a sound",
             len(plan), sum(1 for _, c in plan if c), len(drawn), len(silent))
    db.log_event(video_id, "plan", "info",
                 f"{len(plan)} cards on {theme}: {sum(1 for _, c in plan if c)} filmed, "
                 f"{len(drawn)} drawn, {len(silent)} silent")
    return True


def _load_sounds():
    import json
    path = Path(__file__).resolve().parent.parent / "assets" / "sounds.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _load_facts():
    import json
    path = Path(__file__).resolve().parent.parent / "assets" / "facts.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _default_sounds():
    from core import sounds
    return sounds


# What to search for, when the subject's own name is not what the sound is called.
SOUND_QUERIES = {
    "cow": "cow moo", "pig": "pig oink", "sheep": "sheep bleat", "horse": "horse neigh",
    "chicken": "chicken cluck", "duck": "duck quack", "goat": "goat bleat",
    "rooster": "rooster crow", "lion": "lion roar", "elephant": "elephant trumpet",
    "tiger": "tiger growl", "bear": "bear growl", "monkey": "monkey call",
    "wolf": "wolf howl", "fox": "fox call", "whale": "whale song",
    "dolphin": "dolphin click", "penguin": "penguin call", "eagle": "eagle cry",
    "owl": "owl hoot", "parrot": "parrot squawk", "swan": "swan call",
    "peacock": "peacock call", "flamingo": "flamingo call", "bee": "bee buzzing",
    "butterfly": "butterfly wings", "dragonfly": "dragonfly wings",
    "tractor": "tractor engine", "fire truck": "fire truck siren", "train": "train horn",
    "airplane": "airplane flying", "helicopter": "helicopter rotor",
    "excavator": "excavator digging", "school bus": "school bus engine",
    "police car": "police siren", "boat": "boat engine", "motorcycle": "motorcycle engine",
}


def _sound_query(subject):
    return SOUND_QUERIES.get(subject.lower(), subject)


def _sound_queries(subject):
    """Several ways of asking, because the judge refuses most of what one query returns."""
    low = subject.lower()
    named = SOUND_QUERIES.get(low)
    out = [named] if named else []
    out += [f"{low} sound", f"{low} call", low]
    seen, unique = set(), []
    for q in out:
        if q and q not in seen:
            seen.add(q)
            unique.append(q)
    return unique
