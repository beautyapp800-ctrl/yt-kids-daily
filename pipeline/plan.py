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


def choose_theme(groups, video_id):
    """Deterministic from the video number, so the same run always plans the same video and
    a rerun after a failure does not quietly become a different video."""
    names = sorted(groups)
    return names[int(video_id) % len(names)]


def choose_subjects(groups, theme, wanted, avoid, rng):
    """`wanted` subjects for the theme, preferring ones the recent videos did not use.

    Falls back to the whole theme, and then to every theme, rather than returning a short
    list: a video of twelve cards is a worse outcome than one that reuses a subject.
    """
    pool = list(groups.get(theme, []))
    rng.shuffle(pool)
    fresh = [s for s in pool if s not in avoid]
    chosen = fresh[:wanted]
    if len(chosen) < wanted:
        chosen += [s for s in pool if s not in chosen][:wanted - len(chosen)]
    if len(chosen) < wanted:
        others = [s for g, items in sorted(groups.items()) if g != theme for s in items]
        rng.shuffle(others)
        chosen += [s for s in others if s not in chosen][:wanted - len(chosen)]
        log.info("theme %r has only %d subjects; %d came from other themes",
                 theme, len(pool), wanted - len(pool))
    return chosen


def theme_of(subject, groups):
    for name, items in groups.items():
        if subject in items:
            return name
    return ""


def dominant_theme(subjects, groups, fallback):
    """The theme most of the chosen subjects actually belong to.

    Not the theme that was asked for. When the catalogue has no clips yet for the intended
    theme the plan fills up from the others, and a video of lions titled "8 Fruit And
    Vegetables for Kids" is a lie a viewer notices in the thumbnail.
    """
    counted = {}
    for s in subjects:
        name = theme_of(s, groups)
        if name:
            counted[name] = counted.get(name, 0) + 1
    if not counted:
        return fallback
    best = max(counted.items(), key=lambda kv: (kv[1], kv[0]))
    return best[0] if best[1] >= len(subjects) / 2 else "animals and machines"


def run(video_id, cfg, account, token, groups, clips=None, sounds_module=None,
        rng=None, facts=None):
    """Write the whole plan into the database. Returns True, or raises with a reason."""
    rng = rng or random.Random(int(video_id) * 7919)
    clips = clips if clips is not None else catalogue.load()
    fact_book = facts if facts is not None else _load_facts()
    wanted = int(cfg.get("cards_per_video", 25))
    # The floor is relative: a configuration asking for eight cards means eight, and should
    # not be refused by a constant written for the full-length format.
    floor = min(MIN_CARDS, wanted)

    theme = choose_theme(groups, video_id)
    avoid = db.subjects_used_recently()
    subjects = choose_subjects(groups, theme, int(wanted * SUBJECT_POOL), avoid, rng)
    log.info("video %s: theme %r, %d candidate subjects", video_id, theme, len(subjects))

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
        sound = None
        if theme_of(subject, groups) in SOUNDED_THEMES:
            try:
                found = sounds_module.search_many(subject, _sound_queries(subject))
                # Every candidate is put to a judge before it is used. Taking the first hit
                # put the click of a push-button torch made by a company called Dolphin on the
                # dolphin card, a MIDI of "Baby Shark" on the shark card, and a person
                # reciting "O is for octopus" on the octopus card - all three titles contain
                # the subject's name, which was the only thing the old filter asked for.
                sound, refused = soundcheck.first_real(subject, found, account, token)
                for bad in refused:
                    log.info("  %s: refused %r - %s", subject, bad["title"][:48], bad["why"][:60])
            except Exception as e:                               # noqa: BLE001
                log.warning("no sound for %s: %s", subject, str(e)[:80])
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
