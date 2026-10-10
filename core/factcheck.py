"""Is the fact true? The one check the structural rules cannot do.

"The banana is yellow like a spoon" is caught by looking at its shape. "A seahorse swims
upside down" is not: it is the right length, it names the thing, it uses no measurements, and
it is false. On a learning channel that costs more than any bad frame - a child is being told
something, and they believe it.

The method is the one that worked on the pictures, in the same shape: never ask a leading
question. A model asked "is this true?" agrees, because agreeing is what the sentence in front
of it suggests. So it is asked to find the error instead - told the statement is going into a
children's video, asked what is wrong with it, and made to give the corrected version. A model
that has to produce a correction cannot pass by nodding.

One judge, because the measurement said so - see docs/fact-accuracy.md. It is the same model
family that wrote the fact, which is not independence in any strong sense, and the honest
reading is that it catches what a careful editor would catch rather than that it knows things.
The four true facts it refused ("a parrot talks like us", "an owl sees in the dark") are ones
a careful editor would also have queried.
"""
import json
import re

from core.llm import complete_json, LLMError
from core.logger import get_logger

log = get_logger("factcheck")

# One judge, measured. Over 54 statements - 37 true, 17 false - the 70b model caught every
# false one and refused 4 true ones; the 8b model caught fewer (15 of 17) and refused 15 of
# the 37, on grounds like "a goat does not ALWAYS climb high" and "a bee does not make honey,
# bees collect nectar", the second of which is itself wrong. Asking both and requiring
# unanimity inherited the 8b model's 41% loss for no gain at all, so it is not asked.
JUDGES = ["@cf/meta/llama-3.3-70b-instruct-fp8-fast"]

SYSTEM = """You check statements that are about to be shown to small children as facts.

You are not here to be agreeable. Your job is to find what is wrong. A statement that is
mostly right but wrong in one detail is wrong: a child will remember the detail.

Judge only whether it is TRUE of the thing in general. Do not reject a statement for being
simple, for leaving things out, or for being about a typical member of a group."""


def _prompt(subject, fact):
    return f"""Statement about a {subject}, written for a child of three:

    "{fact}"

Is every part of it true?

Examples of the judgement wanted:
- "A seahorse swims upside down." -> false. Seahorses swim upright.
- "A ladybug has red spots." -> false. The spots are black; the wing cases are red.
- "An octopus has eight arms." -> true.
- "A spider makes a web." -> true, even though a few spiders do not.
- "A cow gives us milk." -> true, even though only the females do.

Return JSON:
{{"true": true or false, "wrong": "what is wrong, or empty", "correct": "a true version"}}"""


def judge(subject, fact, account, token, model):
    """(is_true, what_is_wrong). is_true is None when the model could not be asked."""
    try:
        data = complete_json(_prompt(subject, fact), SYSTEM, account, token,
                             model=model, max_tokens=200, temperature=0.1)
    except LLMError as e:
        log.warning("%s could not judge %r: %s", model, fact[:40], str(e)[:90])
        return None, ""
    if not isinstance(data, dict):
        return None, ""
    verdict = data.get("true")
    if isinstance(verdict, str):
        verdict = verdict.strip().lower() in ("true", "yes")
    wrong = str(data.get("wrong") or "").strip()
    if verdict is None:
        return None, wrong
    return bool(verdict), wrong


def check(subject, fact, account, token, models=None):
    """A fact passes only if every judge asked says it is true.

    Unanimity, not a majority: a false fact that one judge spots is a false fact. The cost is
    some true facts refused, which costs nothing at all - there are always more facts.
    """
    models = models or JUDGES
    verdicts, complaints = [], []
    for model in models:
        ok, wrong = judge(subject, fact, account, token, model)
        verdicts.append(ok)
        if ok is False and wrong:
            complaints.append(f"{model.split('/')[-1]}: {wrong}")
    answered = [v for v in verdicts if v is not None]
    if not answered:
        return {"passed": None, "why": "no judge could be reached", "verdicts": verdicts}
    return {"passed": all(answered), "why": "; ".join(complaints)[:300],
            "verdicts": verdicts}
