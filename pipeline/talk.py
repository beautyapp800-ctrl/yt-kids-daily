"""What is actually said on a card, and around the video.

The first version was a list: name, gap, fact. This is the same card as a short exchange -
ask, wait, answer - because that is what holds a three-year-old and a list does not.

    Listen!   [the sound]   Who makes that sound?   <a second>   It's a cow!   A cow gives us milk.

A card with no sound cannot ask that question, so it asks a different one and keeps the gap
where the child repeats the word:

    Look!   A cow.   <the gap>   A cow gives us milk.

The wording varies from card to card, deterministically from the card's position, so a
twenty-five card video does not say "Who makes that sound?" twenty-five times. The variation
is in the asking, never in the name or the fact: those are the lesson.
"""

LISTEN_CUES = ["Listen!", "Shh, listen!", "Listen to this!", "Can you hear?"]
SOUND_QUESTIONS = ["Who makes that sound?", "What was that?", "Do you know who that is?",
                   "Who could that be?"]
LOOK_CUES = ["Look!", "Look at this!", "Oh, look!", "Look who it is!"]
NAME_QUESTIONS = ["Do you know what this is?", "What is this?", "Can you say it?",
                  "Do you know this one?"]

INTRO = ("Hello! Let us look at some {theme} together. "
         "Can you say their names with me?")
OUTRO = ("That was all of them. You did so well! "
         "Come back soon and we will learn some more. Bye bye!")


def card_segments(idx, subject, fact, sound_path, cfg):
    """The segments of one card, for core.tts.build.

    `idx` picks the wording, so the same card always sounds the same on a rerun and
    neighbouring cards never use the same phrasing.
    """
    name = subject.strip().rstrip(".").title()
    article = "An" if name[0].lower() in "aeiou" else "A"
    before = float(cfg.get("pause_before_name_ms", 450)) / 1000
    after = float(cfg.get("pause_after_name_ms", 900)) / 1000
    think = float(cfg.get("pause_to_think_ms", 1100)) / 1000
    between = float(cfg.get("pause_between_cards_ms", 700)) / 1000

    segments = [("gap", before)]
    if sound_path:
        segments += [
            ("say", LISTEN_CUES[idx % len(LISTEN_CUES)], "cue"),
            ("gap", 0.35),
            ("sound", sound_path),
            ("gap", 0.35),
            ("say", SOUND_QUESTIONS[idx % len(SOUND_QUESTIONS)], "question"),
            ("gap", think),
            ("say", f"It's {article.lower()} {name.lower()}!", "answer"),
            ("gap", after),
            ("say", fact, "fact"),
        ]
    else:
        segments += [
            ("say", LOOK_CUES[idx % len(LOOK_CUES)], "cue"),
            ("gap", 0.3),
            ("say", NAME_QUESTIONS[idx % len(NAME_QUESTIONS)], "question"),
            ("gap", think),
            ("say", f"{article} {name.lower()}.", "name"),
            ("gap", after),
            ("say", fact, "fact"),
        ]
    segments.append(("gap", between))
    return segments


def intro_segments(theme, cfg):
    return [("gap", 0.4), ("say", INTRO.format(theme=theme.lower()), "cue"), ("gap", 0.6)]


def outro_segments(cfg):
    return [("gap", 0.5), ("say", OUTRO, "answer"), ("gap", 0.8)]
