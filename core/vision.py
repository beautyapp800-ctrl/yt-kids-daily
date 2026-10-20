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


# Subjects where the word in front is the subject, not a kind of it. A child learning
# "school bus" has to see a yellow school bus; the inside of a city bus teaches the wrong
# word, and the head-noun fallback let exactly that through. For "sea turtle" the opposite is
# true - any turtle will do - so this is a short list and not a rule about compound words.
STRICT_PHRASE = {"school bus", "police car", "fire truck"}


def _forms(word):
    """A word and the plural or singular a model is as likely to use.

    Written out rather than left as word + "s", which is what it was: the describer answered
    "tomatoes" for a frame of tomatoes and the check compared it against "tomatos", so a
    perfectly good clip was thrown away by a spelling rule. That was the only good frame lost
    in the whole measurement - the models had not made a single mistake on it.
    """
    w = word.lower()
    out = {w}
    if w.endswith(("s", "x", "z", "ch", "sh")):
        out.add(w + "es")
    elif w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
        out.add(w[:-1] + "ies")
    elif w.endswith("o"):
        out.update({w + "es", w + "s"})
    elif w.endswith("fe"):
        out.add(w[:-2] + "ves")
    elif w.endswith("f"):
        out.add(w[:-1] + "ves")
    else:
        out.add(w + "s")
    for suffix, back in (("ies", "y"), ("oes", "o"), ("ves", "f"), ("es", ""), ("s", "")):
        if w.endswith(suffix) and len(w) > len(suffix):
            out.add(w[:-len(suffix)] + back)
    return {f for f in out if f}


def _phrase_forms(phrase):
    """The phrase, and the phrase with its last word pluralised - "school buses", not "buses"."""
    parts = phrase.split()
    if not parts:
        return set()
    return {" ".join(parts[:-1] + [f]) for f in _forms(parts[-1])}


def names_subject(subject, text):
    """Whether `text` names the subject, allowing for the words a model would really use.

    For most subjects the head noun is enough and is wanted: any turtle will do for "sea
    turtle". For the few in STRICT_PHRASE it is not, and only multi-word forms count - the
    first version of this filtered the bare head out and then put it straight back by adding
    the plural forms of every synonym's last word, so "bus" still matched "school bus".
    """
    low_subject = subject.lower()
    given = set(SYNONYMS.get(low_subject, [])) | {low_subject}
    if low_subject in STRICT_PHRASE:
        words = set()
        for w in given:
            if len(w.split()) > 1:
                words |= _phrase_forms(w)
        words |= _phrase_forms(low_subject)
    else:
        words = set(given)
        words |= _forms(low_subject.split()[-1])
        words |= {f for w in given for f in _forms(w.split()[-1])}
        words |= {f for w in given if len(w.split()) > 1 for f in _phrase_forms(w)}
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
    # Measured on 59 frames already judged by eye: the describer alone rejected 9 of the 12
    # frames that showed the wrong thing and threw away none of the 29 good ones, while the
    # classifier threw away 5 good ones - it has no way to say "nothing much", so a sunset
    # comes back as a confident guess at something. Taking either vote as a pass was worse
    # than the describer alone. So the describer decides, and the classifier only stands in
    # when the describer could not be reached.
    out["shows_it"] = (out["by_describer"] if out["by_describer"] is not None
                       else out["by_classifier"])
    return out


# --- what else is in the frame -------------------------------------------------------------

DETECTOR = "@cf/facebook/detr-resnet-50"
DETECT_MIN_SCORE = 0.5
PERSON_MIN_SCORE = 0.8

# Words the describer uses for something built. A fence is not on the list: a tiger in front of
# a blurred zoo fence is still a tiger, and the frame was the best of thirty on the cover.
STRUCTURE_WORDS = {"building", "buildings", "house", "houses", "wall", "walls", "platform",
                   "window", "windows", "roof", "tower", "stadium", "stage", "skyscraper",
                   "aquarium", "tank", "pool", "glass", "bridge", "street", "city"}


# Words the describer uses for a person. A person counts only when the detector AND the
# describer both see one: on its own the detector counted twelve "people" in a colony of king
# penguins, and a person on a spider's web.
PEOPLE_WORDS = {"man", "men", "woman", "women", "person", "people", "child", "children",
                "boy", "girl", "baby", "kid", "kids", "hand", "hands", "visitor", "visitors",
                "trainer", "trainers", "crowd", "tourist", "tourists", "chef", "cook",
                "worker", "workers", "pilot", "rider", "driver", "fisherman"}


def detect(image_path, account, token, model=DETECTOR):
    """[(label, score, (x0, y0, x1, y1) as fractions of the frame)], from an object detector.

    The labels are often wrong - it calls a lion a dog and a tiger a cat, because its classes
    are COCO's eighty - but the boxes are right, and the box is what is used: how much of the
    frame the main thing fills, and whether there are people in it besides.
    """
    from PIL import Image
    with Image.open(image_path) as im:
        width, height = im.size
    rows = _call(account, token, model, Path(image_path).read_bytes(), binary=True) or []
    out = []
    for row in rows:
        box = row.get("box") or {}
        score = float(row.get("score") or 0)
        if score < DETECT_MIN_SCORE or not box:
            continue
        out.append((str(row.get("label", "")).lower(), score,
                    (box["xmin"] / width, box["ymin"] / height,
                     box["xmax"] / width, box["ymax"] / height)))
    return out


def _area(box):
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _inside(inner, outer):
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def frame_contents(detections, listed=""):
    """{subject_area, people, structures} from a detection and the describer's list.

    subject_area  the largest box that is not a person, as a share of the frame - or None when
                  the detector recognised nothing. That is not the same as small: its classes
                  are COCO's eighty, so a strawberry filling the screen, a jellyfish or a whale
                  get no box at all. Checked by eye on all 216 catalogue frames: below 2% with
                  a box, the thing really is a speck (a cow across a valley, a tractor from the
                  air); above it the box under-measures (a lion filling a quarter of the frame
                  reads 4%), so the number is a floor and not a scale;
    people        persons the detector is sure of, outside the subject's own box (the man
                  rowing belongs to the boat), and only if the describer also names a person.
                  Either alone is wrong too often: the detector counts penguins as people, the
                  describer invents a woman at an orca show where there were trainers anyway;
    structures    built things the describer names. The noisiest of the three - it says
                  "building" for a chicken in an empty field - so it lowers a frame's chances
                  rather than ruling it out.
    """
    things = [(l, s, b) for l, s, b in detections if l != "person"]
    subject = max(things, key=lambda d: _area(d[2]), default=None)
    subject_box = subject[2] if subject else None
    seen = [b for l, s, b in detections if l == "person" and s >= PERSON_MIN_SCORE
            and not (subject_box and _inside(b, subject_box))]
    words = set(re.findall(r"[a-z]+", (listed or "").lower()))
    confirmed = bool(words & PEOPLE_WORDS)
    return {"subject_area": round(_area(subject_box), 4) if subject_box else None,
            "people": len(seen) if confirmed else 0,
            "people_detected": len(seen),
            "structures": sorted(words & STRUCTURE_WORDS)}


def list_contents(image_path, account, token, model=DESCRIBER):
    """Everything the describer says it sees, as it said it. An open question again: asked
    "are there people?" it agrees; asked for a list, it has to produce one."""
    payload = {"image": list(Path(image_path).read_bytes()),
               "prompt": "List every kind of thing you can see in this photograph, "
                         "separated by commas. Include the background.",
               "max_tokens": 60}
    result = _call(account, token, model, payload)
    return str((result or {}).get("description") or (result or {}).get("response") or "")


def inspect_frame(image_path, account, token, list_structures=True):
    """frame_contents for one picture, calling the two models it needs."""
    detections = detect(image_path, account, token)
    listed = list_contents(image_path, account, token) if list_structures else ""
    return {**frame_contents(detections, listed), "listed": listed[:400]}
