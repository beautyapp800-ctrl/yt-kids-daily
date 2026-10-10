"""The clip catalogue: which footage exists for which subject, and how good it is.

Searching at run time does not work. Pixabay's tags are honest but its framing is not: a clip
tagged "train" showed a bridge at sunset, one tagged "shark" a surfer. So every clip is put to
a vision model once - "what is the main subject of this photograph?" - and only the confirmed
ones are written into assets/clips.json, with the licence, because the repository is public.

Measured on 59 frames already judged by eye: the model rejects 9 of the 12 that show the wrong
thing and throws away none of the 29 good ones. That is what lets the catalogue grow by itself
instead of somebody looking at frames every week.

Ranking inside a subject. The classifier's confidence in the label that matches the subject
turns out to measure framing rather than identity: across those 59 frames it was a median of
1.00 for clips where the animal fills the frame and 0.00 for clips where it is a speck in an
aerial shot. Eleven of the eighteen distant ones scored under 0.20, against five of the
twenty-nine good ones. Too lossy to refuse on - it would cost one good subject in six - but
free as an ordering, so the best-framed clip of a subject is simply the first one offered.

A clip is never used twice in one video. A single frame of a rooster can honestly answer both
"chicken" and "rooster", and the model is right to confirm it for both, but a child watching
sees the same picture twice and the video looks broken. pick_clips() enforces that, which is
why each subject keeps several clips and not just its best.
"""
import json
import urllib.request
from pathlib import Path

from core.logger import get_logger

log = get_logger("catalogue")

CATALOGUE = Path(__file__).resolve().parent.parent / "assets" / "clips.json"
KEEP_PER_SUBJECT = 4             # enough that two cards in one video never collide
CANDIDATES_PER_SUBJECT = 12      # how many search results are put to the model


def load(path=CATALOGUE):
    if not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(data, path=CATALOGUE):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def prominence(labels, subject, names_subject):
    """How sure the classifier is of the label that matches - a proxy for how big the subject
    is in the frame, not for whether it is there. See the module docstring for the numbers."""
    scores = [s for l, s in labels if names_subject(subject, l)]
    return max(scores) if scores else 0.0


def pick_clips(subjects, catalogue, used=None):
    """[(subject, clip or None)] for one video, never repeating a clip.

    `used` lets a caller carry exclusions in from outside - a clip that served yesterday's
    video is fine to use again today, but one already on a card in THIS video is not.
    """
    used = set(used or ())
    out = []
    for subject in subjects:
        chosen = None
        for clip in catalogue.get(subject, {}).get("clips", []):
            if clip["id"] not in used:
                chosen = clip
                used.add(clip["id"])
                break
        if chosen is None and catalogue.get(subject, {}).get("clips"):
            log.info("every clip for %s is already in this video; it will be drawn instead",
                     subject)
        out.append((subject, chosen))
    return out


def _thumbnail(url, dst):
    req = urllib.request.Request(url, headers={"User-Agent": "yt-kids/0.1"})
    with urllib.request.urlopen(req, timeout=90) as r:
        Path(dst).write_bytes(r.read())
    return dst


def verify_subject(subject, hits, account, token, work_dir, vision, keep=KEEP_PER_SUBJECT):
    """Put each candidate to the model and return the ones it confirms, best framed first.

    Returns (kept, rejected). Rejected clips are kept in the catalogue too, with what the
    model said they were - a rejection nobody can see is a rejection nobody can check, and
    the only way to notice the verifier going wrong is to be able to read its refusals.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    kept, rejected = [], []
    for hit in hits[:CANDIDATES_PER_SUBJECT]:
        if not hit.get("thumbnail"):
            continue
        frame = work / f"{subject.replace(' ', '_')}_{hit['id']}.jpg"
        try:
            if not frame.exists():
                _thumbnail(hit["thumbnail"], frame)
            check = vision.verify(frame, subject, account, token)
        except Exception as e:                                   # noqa: BLE001
            log.warning("%s clip %s could not be checked: %s", subject, hit["id"], e)
            continue
        row = {"id": hit["id"], "url": hit.get("url"), "seconds": hit.get("seconds"),
               "width": hit.get("width"), "licence": hit.get("licence"),
               "attribution_required": hit.get("attribution_required", False),
               "clip": hit.get("clip"), "thumbnail": hit.get("thumbnail"),
               "said": check.get("description", ""),
               "prominence": round(prominence(check.get("labels") or [], subject,
                                              vision.names_subject), 3)}
        if check.get("shows_it"):
            kept.append(row)
        else:
            rejected.append({**row, "why": "the model called it "
                                           f"{check.get('description') or 'something else'}"})
        if len(kept) >= keep:
            break
    kept.sort(key=lambda c: -c["prominence"])
    return kept, rejected
