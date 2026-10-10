"""What is said on a card, and around the video.

Measured against the format that works rather than guessed at. Kiddopedia's "OCEAN ANIMALS
Names and Sounds" has 4.5 million views: 357 seconds, about 36 cards, chapter marks at 0:06,
0:16, 0:26, 0:36, 0:46 - **ten seconds a card, metronomically**, with a six-second opening and
no talk between cards at all.

The first version of this file ran 14 to 18 seconds a card and filled the time with an
exchange on every single one. That is nearly twice the pace that holds a toddler, and the
exchange is what made it slow: "Listen - [sound] - who makes that sound? - ... - it's a
dolphin! - a dolphin jumps out of the water" is six beats where the format wants three.

So the default card is three beats and about ten seconds:

    Dolphin!   [the sound]   A dolphin jumps out of the water!

and the question is kept for every ASK_EVERY-th card, where it is a change of pace rather
than the pattern. That is the thing a child notices: not that they are asked, but that this
one is different from the last four.
"""

ASK_EVERY = 4            # a question on every fourth card, not on all of them

LISTEN_CUES = ["Listen!", "Shh, listen!", "Hear that?", "Listen to this!"]
LOOK_CUES = ["Look!", "Look at this!", "Oh, look!", "Wow, look!"]
SOUND_QUESTIONS = ["Who makes that sound?", "What was that?", "Who could that be?"]
NAME_QUESTIONS = ["Do you know this one?", "What is this?", "Can you say it?"]

INTRO = "Hello! Let's learn some {theme}. Are you ready? Let's go!"
OUTRO = "That was all of them! You did so well. Bye bye!"


def _article(name):
    return "An" if name[:1].lower() in "aeiou" else "A"


def card_segments(idx, subject, fact, sound_path, cfg):
    """The segments of one card, for core.tts.build.

    `idx` chooses the wording and whether this is a question card, so a rerun of the same
    video says the same thing and neighbouring cards never sound alike.
    """
    name = subject.strip().rstrip(".").title()
    asking = (idx % ASK_EVERY) == ASK_EVERY - 1
    think = float(cfg.get("pause_to_think_ms", 900)) / 1000
    after = float(cfg.get("pause_after_name_ms", 700)) / 1000
    between = float(cfg.get("pause_between_cards_ms", 350)) / 1000

    if sound_path and not asking:
        # The common card: name it, hear it, one thing about it.
        segments = [
            ("say", f"{name}!", "name"),
            ("gap", 0.25),
            ("sound", sound_path),
            ("gap", 0.25),
            ("say", fact, "fact"),
        ]
    elif sound_path:
        segments = [
            ("say", LISTEN_CUES[idx % len(LISTEN_CUES)], "cue"),
            ("gap", 0.2),
            ("sound", sound_path),
            ("gap", 0.2),
            ("say", SOUND_QUESTIONS[idx % len(SOUND_QUESTIONS)], "question"),
            ("gap", think),
            ("say", f"{_article(name).lower()} {name.lower()}!".capitalize(), "answer"),
            ("gap", 0.2),
            ("say", fact, "fact"),
        ]
    elif asking:
        segments = [
            ("say", LOOK_CUES[idx % len(LOOK_CUES)], "cue"),
            ("gap", 0.2),
            ("say", NAME_QUESTIONS[idx % len(NAME_QUESTIONS)], "question"),
            ("gap", think),
            ("say", f"{name}!", "name"),
            ("gap", after),
            ("say", fact, "fact"),
        ]
    else:
        segments = [
            ("say", f"{name}!", "name"),
            ("gap", after),
            ("say", fact, "fact"),
        ]
    segments.append(("gap", between))
    return segments


def intro_segments(theme, cfg):
    return [("gap", 0.2), ("say", INTRO.format(theme=theme.lower()), "cue"), ("gap", 0.3)]


def outro_segments(cfg):
    return [("gap", 0.3), ("say", OUTRO, "answer"), ("gap", 0.5)]
