"""The words of a video: a list of subjects, and one short fact for each.

The format is fixed and narrow - shown, named, one thing about it, twenty-five times - so
almost all of the writing is in what the fact may not be. A fact for a three-year-old has to
be picturable and countable in their world: "the blue whale is bigger than a bus" works
because they have seen a bus. "The blue whale can weigh 150 tonnes" is the same fact and
means nothing, because a tonne is not a thing you have seen.

The rules the code enforces, rather than hopes for:

- at most FACT_MAX_WORDS words, which at this speaking rate is about four seconds;
- no numbers above ten, no units of measurement, and no comparisons to anything a small
  child has not held or stood next to;
- no word longer than LONG_WORD letters, which is a blunt instrument and a good one: it
  catches "approximately", "carnivorous" and "echolocation" without needing a vocabulary list;
- one sentence, ending in a full stop.

Anything rejected is sent back to the model with the reason, three times, and after that the
subject is dropped from the video rather than carried with a bad fact. A video of 25 cards
does not miss one; a child told something they cannot picture learns that this is a programme
where they do not understand things.
"""
import re

from core.llm import complete_json
from core.logger import get_logger

log = get_logger("cards")

ATTEMPTS = 3
FACT_MAX_WORDS = 12
FACT_MIN_WORDS = 4
LONG_WORD = 10

# Units mean nothing to a three-year-old, and a number they cannot count to means nothing
# either. Both are the same mistake: a fact stated in a scale the child does not own.
UNITS = {"tonne", "tonnes", "ton", "tons", "kilogram", "kilograms", "kg", "pound", "pounds",
         "metre", "metres", "meter", "meters", "centimetre", "centimetres", "foot", "feet",
         "inch", "inches", "mile", "miles", "kilometre", "kilometres", "km", "litre",
         "litres", "gallon", "gallons", "degree", "degrees", "percent", "mph", "year",
         "years", "century", "centuries", "million", "billion", "thousand"}

SYSTEM = """You write the words for a learning video for children aged two to six.

Each card shows a real thing, names it, and tells the child one thing about it. You are
writing that one thing. The child is three. They have seen a bus, a ball, a cat, a house, a
spoon, their own hand. They have not seen a tonne, a metre, a continent or a century.

Write the way a parent speaks to a child on their lap: short, warm, certain, present tense."""


# "The banana is yellow like a spoon." Every fact in the first run came out of this mould,
# and a third of them were false, because the comparison was reached for before the fact was.
LIKE_A_TEMPLATE = re.compile(r"^(the|a|an)\s+[\w\s]+?\s+(is|are|has|have)\s+[\w\s]*?\s*"
                             r"like\s+(a|an|the)\s+\w+\s*\.$", re.I)
FILLER_END = re.compile(r"\b(now|too|also|as well|very much)\s*\.$", re.I)


def _words(text):
    return re.findall(r"[A-Za-z']+", text or "")


def fact_problems(fact, subject):
    """Why a fact is unusable. An empty list means it passes."""
    out = []
    text = (fact or "").strip()
    words = _words(text)
    if not words:
        return ["the fact is empty"]
    if not FACT_MIN_WORDS <= len(words) <= FACT_MAX_WORDS:
        out.append(f'"{text}" is {len(words)} words, needs {FACT_MIN_WORDS} to {FACT_MAX_WORDS}')
    if not text.endswith("."):
        out.append(f'"{text}" does not end in a full stop')
    if text.count(".") > 1 or ";" in text:
        out.append(f'"{text}" is more than one sentence')
    long_words = [w for w in words if len(w) > LONG_WORD]
    if long_words:
        out.append(f'"{text}" uses {", ".join(long_words)}, too long a word for a three-year-old')
    units = [w for w in words if w.lower() in UNITS]
    if units:
        out.append(f'"{text}" measures in {", ".join(units)}, which a small child has no idea of')
    for number in re.findall(r"\d+", text):
        if int(number) > 10:
            out.append(f'"{text}" says {number}, past what a three-year-old can count to')
            break
    if subject.lower().split()[-1] not in text.lower():
        out.append(f'"{text}" does not mention the {subject}')
    if LIKE_A_TEMPLATE.match(text):
        out.append(f'"{text}" is the "X is something like a Y" template. Asked for a list of '
                   f"things a child has seen, the model used them as a crutch and produced "
                   f'"the banana is yellow like a spoon" and "the octopus has many legs like '
                   f'a cat". Say what the thing DOES or HAS instead')
    if FILLER_END.search(text):
        out.append(f'"{text}" ends on a filler word')
    return out


def _prompt(subjects, complaints=()):
    listed = "\n".join(f"- {s}" for s in subjects)
    prompt = f"""Write one fact about each of these, for a child of three:

{listed}

Every fact must be TRUE and must be about THAT thing in particular. The best facts say what
the thing does or what it has:

  Octopus    An octopus has eight arms.
  Bee        A bee makes honey in a hive.
  Fire truck A fire truck sprays water on a fire.
  Penguin    A penguin swims but cannot fly.
  Banana     A banana grows on a tall green plant.
  Whale      A whale is bigger than a bus.

Note the last one: a comparison is allowed, but only when it is true and it helps. Do not
reach for one. "The banana is yellow like a spoon" is false and says nothing; "the octopus
has many legs like a cat" is false twice over. If you cannot think of a true comparison,
say what the thing does instead - that is almost always better anyway.

Rules, all of them hard:
- Between {FACT_MIN_WORDS} and {FACT_MAX_WORDS} words. One sentence, ending in a full stop.
- A child of three must be able to picture it. No measurements of any kind, no numbers above
  ten, nothing about continents, centuries, species or weight.
- No word longer than {LONG_WORD} letters.
- Name the thing in the fact.
- Present tense. Not a question. No filler words at the end.
- Every fact different from the others: not twenty-five sentences of the same shape.

Return JSON: {{"facts": {{"subject": "the fact.", ...}}}} with one entry per subject above."""
    if complaints:
        listed = "\n".join(f"- {c}" for c in complaints[:8])
        prompt += ("\n\nYour previous answer had these faults. Fix every one and introduce "
                   f"no new ones:\n{listed}")
    return prompt


def write_facts(subjects, account, token, attempts=ATTEMPTS):
    """({subject: fact}, [subjects that could not be written]).

    Asked in one call for all of them, because the model writing twenty-five facts at once
    can see that it has already used "lives in the ocean" and vary; asked one at a time it
    repeats itself, which over a whole video is the thing a parent notices first.
    """
    facts, complaints, wanted = {}, [], list(subjects)
    for attempt in range(1, attempts + 1):
        if not wanted:
            break
        data = complete_json(_prompt(wanted, complaints), SYSTEM, account, token,
                             max_tokens=120 + 60 * len(wanted), temperature=0.85)
        got = (data or {}).get("facts") if isinstance(data, dict) else None
        if not isinstance(got, dict):
            complaints = ["the answer was not a JSON object with a 'facts' key"]
            continue
        complaints, still = [], []
        for subject in wanted:
            fact = str(got.get(subject) or "").strip()
            problems = fact_problems(fact, subject)
            if problems:
                complaints.extend(problems)
                still.append(subject)
            else:
                facts[subject] = fact
        wanted = still
        if wanted:
            log.warning("attempt %d/%d: %d fact(s) rejected (%s)", attempt, attempts,
                        len(wanted), "; ".join(complaints[:2]))
    if wanted:
        log.error("no usable fact for %s after %d attempts; those cards are dropped",
                  ", ".join(wanted), attempts)
    return facts, wanted
