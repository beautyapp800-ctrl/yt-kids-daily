"""Measure what else is in each catalogue frame, once, and store it with the clip.

    python scripts/inspect_frames.py            # every clip not measured yet
    python scripts/inspect_frames.py --again    # every clip

For each clip: how much of the frame the main thing fills, how many people are in it besides,
and what built things the describer names. The cover reads these; nothing in the daily run asks
a model. New clips get them when they are added (pipeline/catalogue.py); this is for the clips
that were added before the measurement existed.

Resumable, and it stops cleanly when the daily allowance runs out: run it again tomorrow.
"""
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core import vision
from pipeline import catalogue
from build_catalogue import credentials

WORK = ROOT / "data" / "candidate-frames"
FIELDS = ("subject_area", "people", "people_detected", "structures")


def _quota_spent(error):
    text = str(error)
    return "429" in text and ("daily free allocation" in text or "neurons" in text)


def frame_for(subject, clip):
    path = WORK / f"{subject.replace(' ', '_')}_{clip['id']}.jpg"
    if not path.exists() and clip.get("thumbnail"):
        WORK.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(clip["thumbnail"], headers={"User-Agent": "yt-kids/0.1"})
        with urllib.request.urlopen(req, timeout=90) as r:
            path.write_bytes(r.read())
    return path if path.exists() else None


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--again", action="store_true")
    parser.add_argument("--detector-only", action="store_true",
                        help="re-run only the detector and reuse the describer's stored list "
                             "- cheap, for when the rules that combine them change")
    args = parser.parse_args(argv)
    account, token = credentials()
    data = catalogue.load()
    todo = [(s, c) for s, e in data.items() for c in e.get("clips", [])
            if args.again or not all(f in c for f in FIELDS)]
    print(f"{len(todo)} clip(s) to measure")
    done = failed = 0
    lock = threading.Lock()
    stop = threading.Event()

    def one(item):
        nonlocal done, failed
        subject, clip = item
        if stop.is_set():
            return
        try:
            frame = frame_for(subject, clip)
            if frame is None:
                with lock:
                    failed += 1
                print(f"  {subject:12} {clip['id']}: no frame to look at", flush=True)
                return
            result = None
            for attempt in range(5):
                try:
                    if args.detector_only and clip.get("listed") is not None:
                        result = {**vision.frame_contents(
                            vision.detect(frame, account, token), clip["listed"]),
                            "listed": clip["listed"]}
                    else:
                        result = vision.inspect_frame(frame, account, token)
                    break
                except vision.VisionError as e:
                    # A 429 is two different things here. "daily free allocation" means the
                    # day's neurons are gone and waiting cannot help; anything else is a rate
                    # limit from asking too fast, which a pause cures. Treating every 429 as the
                    # first stopped a run 49 clips short while the allowance was still open.
                    if "429" not in str(e) or _quota_spent(e) or attempt == 4:
                        raise
                    time.sleep(5 * (attempt + 1))
        except Exception as e:                                   # noqa: BLE001
            if _quota_spent(e):
                stop.set()
                print(f"stopped: the daily allowance is spent ({str(e)[:80]}). Run again later.",
                      flush=True)
                return
            with lock:
                failed += 1
            print(f"  {subject:12} {clip['id']}: {str(e)[:90]}", flush=True)
            return
        with lock:
            clip.update(result)
            done += 1
            if done % 10 == 0:
                catalogue.save(data)
        area = "no box" if clip["subject_area"] is None else f"{clip['subject_area']:.1%}"
        print(f"  {subject:12} {clip['id']:>7}  fills {area:>6}  "
              f"people {clip['people']}  built {','.join(clip['structures']) or '-'}", flush=True)

    # Two at a time: each clip is two model calls and most of the time is waiting on them.
    # Four ran into the per-minute rate limit.
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(one, todo))
    catalogue.save(data)
    left = sum(1 for e in data.values() for c in e.get("clips", [])
               if not all(f in c for f in FIELDS))
    print(f"\nmeasured {done}, could not {failed}, still to do {left}")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
