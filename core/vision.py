"""Ask a model whether the picture really shows the thing we searched for.

This is the step the whole project turned on. A clip's tags say "train"; the frame shows a
bridge at sunset. No amount of reading metadata catches that, and curating by eye does not
survive past the third video - sixty subjects is two videos, and then the themes run out and
somebody has to sit and look at frames every week. So the looking has to be done by a model.

Two are asked, because they fail in different directions:

  classify  @cf/microsoft/resnet-50 returns ImageNet labels. It is quick and certain, and its
            thousand classes happen to cover most of this list - tiger shark, African
            elephant, school bus, fire engine, tractor are all ImageNet classes. What it
            cannot do is say "nothing much": it always returns its best thousand-way guess,
            so a picture of a sunset comes back as something, confidently.

  describe  a vision-language model is asked what the main subject is, in two words. It can
            say "sunset" for a sunset, which is the whole point, but it is slower and it
            will happily agree with a leading question, so it is never asked "is this a
            whale" - only "what is this".

A frame passes when either model names the subject, and the synonym table is what makes
"tiger shark" count as a shark and "jetliner" as an aeroplane. Both numbers - what each model
catches and what each wrongly rejects - are measured on frames already judged by eye before
any of this is trusted.
"""
import base64
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from core.logger import get_logger

log = get_logger("vision")

CLASSIFIER = "@cf/microsoft/resnet-50"
DESCRIBER = "@cf/llava-hf/llava-1.5-7b-hf"
API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
TIMEOUT = 90

# How sure the classifier has to be before its answer is worth anything at all. Below this it
# is guessing, and a guess that happens to contain the right word is not evidence.
MIN_SCORE = 0.10
TOP_N = 5

# ImageNet says "tiger shark" where we say "shark", and "jetliner" where we say "airplane".
# Only the subjects whose everyday name is not an ImageNet class need an entry; for the rest
# the word itself is matched, including as part of a longer label.
SYNONYMS = {
    "shark": ["shark", "tiger shark", "great white", "hammerhead"],
    "whale": ["whale", "grey whale", "gray whale", "killer whale", "humpback"],
    "airplane": ["airliner", "jetliner", "warplane", "wing", "airplane", "aeroplane", "plane"],
    "school bus": ["school bus", "schoolbus", "minibus", "trolleybus", "bus"],
    "police car": ["police van", "police car", "patrol", "squad car", "cab", "limousine"],
    "fire truck": ["fire engine", "fire truck"],
    "motorcycle": ["motor scooter", "moped", "motorcycle", "motorbike"],
    "train": ["locomotive", "steam locomotive", "electric locomotive", "passenger car",
              "freight car", "bullet train", "train"],
    "boat": ["canoe", "speedboat", "lifeboat", "fireboat", "yawl", "catamaran", "trimaran",
             "boat", "ship", "gondola", "paddle"],
    "tractor": ["tractor", "thresher", "harvester", "plow", "plough"],
    "excavator": ["power shovel", "steam shovel", "excavator", "bulldozer", "backhoe"],
    "helicopter": ["helicopter", "chopper"],
    "sea turtle": ["loggerhead", "leatherback", "sea turtle", "turtle", "terrapin"],
    "starfish": ["starfish", "sea star", "brain coral"],
    "jellyfish": ["jellyfish"],
    "seahorse": ["sea horse", "seahorse"],
    "octopus": ["octopus", "squid", "nematode"],
    "crab": ["rock crab", "fiddler crab", "king crab", "hermit crab", "dungeness", "crab"],
    "chicken": ["hen", "cock", "chicken", "partridge"],
    "rooster": ["cock", "rooster", "hen"],
    "cow": ["ox", "oxen", "water buffalo", "bison", "cow", "cattle"],
    "sheep": ["ram", "bighorn", "ewe", "sheep"],
    "pig": ["hog", "wild boar", "pig", "swine"],
    "goat": ["ibex", "mountain goat", "goat"],
    "monkey": ["macaque", "baboon", "langur", "capuchin", "spider monkey", "marmoset",
               "guenon", "titi", "monkey", "chimpanzee", "gorilla", "orangutan"],
    "bear": ["brown bear", "black bear", "ice bear", "sloth bear", "bear"],
    "elephant": ["tusker", "indian elephant", "african elephant", "elephant"],
    "butterfly": ["butterfly", "admiral", "monarch", "ringlet", "lycaenid", "sulphur"],
    "bee": ["bee", "honeycomb", "apiary"],
    "ant": ["ant", "termite"],
    "ladybug": ["ladybug", "ladybird", "leaf beetle"],
    "dragonfly": ["dragonfly", "damselfly", "darning needle"],
    "spider": ["spider", "tarantula", "garden spider", "black widow", "wolf spider"],
    "owl": ["owl", "great grey owl", "great grey"],
    "eagle": ["bald eagle", "eagle", "kite", "vulture"],
    "parrot": ["macaw", "parrot", "lorikeet", "cockatoo", "african grey"],
    "swan": ["black swan", "swan", "goose"],
    "peacock": ["peacock"],
    "flamingo": ["flamingo"],
    "penguin": ["king penguin", "penguin"],
    "banana": ["banana"],
    "apple": ["granny smith", "apple"],
    "orange": ["orange", "lemon"],
    "strawberry": ["strawberry"],
    "watermelon": ["watermelon"],
    "carrot": ["carrot"],
    "tomato": ["tomato"],
    "broccoli": ["broccoli", "cauliflower"],
    "grapes": ["grape", "grapes"],
    "pineapple": ["pineapple", "ananas"],
    "horse": ["sorrel", "horse", "pony", "stallion", "mare"],
    "zebra": ["zebra"],
    "giraffe": ["giraffe"],
    "lion": ["lion"],
    "tiger": ["tiger"],
    "wolf": ["timber wolf", "white wolf", "wolf", "coyote"],
    "fox": ["red fox", "kit fox", "arctic fox", "grey fox", "fox"],
    "kangaroo": ["wallaby", "kangaroo"],
    "dolphin": ["dolphin", "grampus", "porpoise"],
    "duck": ["drake", "duck", "merganser", "mallard"],
}


class VisionError(Exception):
    pass


def _call(account, token, model, payload, binary=False):
    url = API.format(account=account, model=model)
    if binary:
        data = payload
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"}
    else:
        data = json.dumps(payload).encode()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        raise VisionError(f"{model}: HTTP {e.code}: {e.read()[:200]}") from e
    except urllib.error.URLError as e:
        raise VisionError(f"{model}: {e.reason}") from e
    if not body.get("success", True):
        raise VisionError(f"{model}: {body.get('errors')}")
    return body.get("result")


def classify(image_path, account, token, model=CLASSIFIER):
    """[(label, score)] from the image classifier, best first."""
    result = _call(account, token, model, Path(image_path).read_bytes(), binary=True)
    rows = result if isinstance(result, list) else (result or {}).get("output") or []
    out = []
    for row in rows[:TOP_N]:
        if isinstance(row, dict) and "label" in row:
            out.append((str(row["label"]).lower(), float(row.get("score") or 0)))
    return out


def describe(image_path, account, token, model=DESCRIBER):
    """What the model says the main subject is, in its own words.

    The question is open on purpose. Asking "is this a whale?" gets "yes" from a model that
    wants to agree; asking "what is this?" makes it commit first.
    """
    payload = {"image": list(Path(image_path).read_bytes()),
               "prompt": "What is the main subject of this photograph? "
                         "Answer with one or two words only, naming the thing itself.",
               "max_tokens": 20}
    result = _call(account, token, model, payload)
    text = (result or {}).get("description") or (result or {}).get("response") or ""
    return re.sub(r"[^a-z ]", " ", str(text).lower()).strip()


def names_subject(subject, text):
    """Whether `text` names the subject, allowing for the words a model would really use."""
    words = SYNONYMS.get(subject.lower(), [subject.lower()])
    if subject.lower() not in words:
        words = words + [subject.lower()]
    head = subject.lower().split()[-1]
    words = words + [head, head + "s", head.rstrip("s")]
    low = f" {text} "
    return any(re.search(rf"\b{re.escape(w)}\b", low) for w in words if w)


def verify(image_path, subject, account, token, use_describer=True):
    """Does this frame show the subject? Returns a dict, and never raises on a model failure:
    a verifier that falls over is a pipeline that stops, and the fallback is to keep the frame
    and say the check did not run."""
    out = {"subject": subject, "labels": [], "description": "", "by_classifier": None,
           "by_describer": None, "errors": []}
    try:
        out["labels"] = classify(image_path, account, token)
        best = [l for l, s in out["labels"] if s >= MIN_SCORE]
        out["by_classifier"] = any(names_subject(subject, l) for l in best)
    except VisionError as e:
        out["errors"].append(str(e)[:160])
    if use_describer:
        try:
            out["description"] = describe(image_path, account, token)
            out["by_describer"] = names_subject(subject, out["description"])
        except VisionError as e:
            out["errors"].append(str(e)[:160])
    votes = [v for v in (out["by_classifier"], out["by_describer"]) if v is not None]
    out["shows_it"] = any(votes) if votes else None
    return out
