"""Is this recording actually the sound the thing makes?

The pictures are checked by a model that looks at them. Sounds had no equivalent, and I wrote
that down as a weaker net - then shipped a video in which the dolphin card played the click of
a push-button torch made by a company called Dolphin, the shark card played a MIDI file of
"Baby Shark", and the octopus card played a person reciting "O is for octopus".

Every one passed the old filter, because the old filter asked only whether the subject's name
was in the title. All three titles contain it.

There is no free classifier that will listen to four seconds of audio and say "dolphin". But
the title and the description say what the recording is, in words, and judging words is
something a language model does well - the same model and the same trick that catches a false
fact: never ask whether it is right, ask what is wrong with it.

    "dolphin torch locking push button.wav" -> a torch, not an animal
    "Baby Shark" (.mid)                     -> a tune, not a shark
    "O is for octopus"                      -> a person saying a word

Two hard rules come first, because they cost nothing: a file that is not a recording at all
(MIDI, which is instructions for a synthesiser) and the alphabet recordings Wikimedia holds
thousands of.
"""
import re
from pathlib import Path

from core.llm import complete_json, LLMError, QuotaExhausted
from core.logger import get_logger

log = get_logger("soundcheck")

JUDGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"

# Not recordings of anything. MIDI is a score, not a sound.
NOT_A_RECORDING = {".mid", ".midi", ".kar", ".xm", ".mod", ".sid"}

# "O is for octopus", "A is for apple" - Wikimedia has a set of these for every letter, and
# they are a person reading an alphabet book.
ALPHABET = re.compile(r"\b[a-z] is for\b|\balphabet\b|\bphonics\b", re.I)

SYSTEM = """You check whether a sound file is really a recording of the thing it is filed under.

A children's learning video plays this sound straight after naming the animal or machine, so
the child learns that this is what it sounds like. A wrong one teaches them something false.

Be suspicious of titles where the word is a brand, a song, a place or a person's name rather
than the creature itself. Say what the recording actually is."""


def _prompt(subject, title, description=""):
    extra = f"\nDescription: {description[:300]}" if description else ""
    return f"""A sound file is about to be used as the real sound of a {subject}.

Title: "{title}"{extra}

Is this a recording of an actual {subject} making its own sound?

Examples of the judgement wanted:
- {subject} = dolphin, title "dolphin torch locking push button.wav" -> false. It is a torch
  of that brand being clicked.
- {subject} = shark, title "Baby Shark" -> false. It is the children's song.
- {subject} = octopus, title "O is for octopus" -> false. A person reciting the alphabet.
- {subject} = cow, title "herd of cows, mooing" -> true.
- {subject} = penguin, title "Little Penguin calls at St Kilda Breakwater" -> true.
- {subject} = tractor, title "Deutz-Tractor-Engine-1972.wav" -> true. A tractor engine is the
  sound a tractor makes.

Return JSON: {{"real": true or false, "what": "what the recording actually is"}}"""


def obviously_wrong(subject, record):
    """The cheap checks, before a model is asked. Returns a reason or None."""
    url = str(record.get("url") or "")
    title = str(record.get("title") or "")
    if Path(url.split("?")[0]).suffix.lower() in NOT_A_RECORDING:
        return f"{Path(url).suffix} is not a recording, it is a score for a synthesiser"
    if ALPHABET.search(title):
        return "an alphabet recording, which is a person saying the word"
    return None


def check(subject, record, account, token, model=JUDGE):
    """{'ok': bool|None, 'why': str}. None means the judge could not be reached."""
    cheap = obviously_wrong(subject, record)
    if cheap:
        return {"ok": False, "why": cheap}
    try:
        data = complete_json(_prompt(subject, record.get("title"),
                                     record.get("description", "")),
                             SYSTEM, account, token, model=model,
                             max_tokens=160, temperature=0.1)
    except QuotaExhausted:
        raise
    except LLMError as e:
        log.warning("could not judge %r: %s", record.get("title"), str(e)[:90])
        return {"ok": None, "why": "the judge could not be reached"}
    if not isinstance(data, dict):
        return {"ok": None, "why": "the judge did not answer in JSON"}
    verdict = data.get("real")
    if isinstance(verdict, str):
        verdict = verdict.strip().lower() in ("true", "yes")
    return {"ok": bool(verdict), "why": str(data.get("what") or "")[:200]}


def first_real(subject, records, account, token, limit=8):
    """The first recording the judge accepts, with the refusals alongside it."""
    refused = []
    for record in records[:limit]:
        verdict = check(subject, record, account, token)
        if verdict["ok"]:
            return record, refused
        if verdict["ok"] is False:
            refused.append({"title": record.get("title"), "why": verdict["why"]})
    return None, refused
