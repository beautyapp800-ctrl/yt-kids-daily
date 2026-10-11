"""One video, start to finish: plan, media, narration, render, SEO, thumbnail, upload.

    python run.py

The shape is yt-factory's, because that shape has been through real failures: the stages are
resumable (a stage already finished for this video is skipped, so a run that died at the
render does not download or narrate twice), a failure is recorded on the video rather than
raised, and a video that has failed MAX_ATTEMPTS times is left alone and the next run starts
a new one.

What is different is how little this spends. The plan reads three catalogues - clips, facts,
sounds - each checked once when it was added, and asks no model anything (tests/test_daily_
cost.py holds that line). The only part of a daily run that can touch the Cloudflare allowance
is drawing a card that has no footage. That is why this project can run every day on the free
tier at all.
"""
import argparse
import json
import sys
from pathlib import Path

from core import db
from core.config import ConfigError, credentials, load_config, output_dir
from core.logger import get_logger

log = get_logger("run")

MAX_ATTEMPTS = db.MAX_ATTEMPTS

# The brief: 6 to 10 minutes. Outside it the video still goes out - a four-minute video is
# not worth losing a day over - but the run says so, in the log and in the email, because a
# channel that quietly drifts to three minutes has stopped being the thing that was designed.
LENGTH_DEFAULTS = {"min_minutes": 6.0, "max_minutes": 10.0}


def _plan(video_id, cfg, account, token):
    from pipeline import plan
    groups = json.loads((Path(__file__).parent / "assets" / "subjects.json")
                        .read_text(encoding="utf-8"))
    return plan.run(video_id, cfg, account, token, groups)


def _media(video_id, cfg, account, token):
    from pipeline import media
    return media.run(video_id, cfg, account, token, db, output_dir(video_id))


def _narrate(video_id, cfg, account, token):
    from pipeline import narrate
    return narrate.run(video_id, cfg, db, output_dir(video_id))


def _render(video_id, cfg, account, token):
    from pipeline import render
    return render.run(video_id, cfg, db, output_dir(video_id), board=True)


def _seo(video_id, cfg, account, token):
    from pipeline import seo
    return seo.run(video_id, cfg, db, output_dir(video_id))


def _thumbnail(video_id, cfg, account, token):
    from pipeline import thumbnail
    return thumbnail.run(video_id, cfg, db, output_dir(video_id))


def _upload(video_id, cfg, account, token):
    from pipeline import upload
    return upload.run(video_id, cfg)


# (stage name, function, video status while the stage runs)
STAGES = [
    ("plan", _plan, "planning"),
    ("media", _media, "media"),
    ("narrate", _narrate, "narrating"),
    ("render", _render, "rendering"),
    # seo before thumbnail, as in yt-factory: the tile is checked against the title so that it
    # does not repeat it.
    ("seo", _seo, "seo"),
    ("thumbnail", _thumbnail, "thumbnail"),
    ("upload", _upload, "uploading"),
]


def length_note(video_id, cfg):
    """None if the finished video is the right length, else one sentence saying how not."""
    gate = {**LENGTH_DEFAULTS, **(cfg.get("length_gate") or {})}
    minutes = (db.get_video(video_id).get("duration_s") or 0) / 60
    if gate["min_minutes"] <= minutes <= gate["max_minutes"]:
        return None
    side = "short" if minutes < gate["min_minutes"] else "long"
    return (f"the video is {minutes:.1f} minutes, too {side} for the "
            f"{gate['min_minutes']:g}-{gate['max_minutes']:g} the channel is designed around")


def process_video(video_id, cfg, account, token):
    """Run every stage for one video. Never raises: a failure is recorded as status=failed."""
    done = db.finished_stages(video_id)
    if done:
        log.info("resuming video %s: %s already finished", video_id,
                 ", ".join(n for n, _f, _s in STAGES if n in done))
    for name, stage, status in STAGES:
        if name in done:
            continue
        try:
            db.update_video(video_id, status=status)
            db.log_event(video_id, name, "info", "stage started")
            if not stage(video_id, cfg, account, token):
                raise RuntimeError(f"stage {name} returned False")
            db.log_event(video_id, name, "info", "stage finished")
            if name == "render":
                note = length_note(video_id, cfg)
                if note:
                    log.warning("video %s: %s", video_id, note)
                    db.log_event(video_id, "render", "warning", note)
        except Exception as e:                                   # noqa: BLE001
            log.error("video %s failed at stage %s: %s", video_id, name, e)
            try:
                db.log_event(video_id, name, "error", str(e))
                db.update_video(video_id, status="failed", error=f"{name}: {e}")
            except Exception as db_err:                          # noqa: BLE001
                log.error("could not record the failure in the DB: %s", db_err)
            return False

    on_youtube = (db.get_video(video_id) or {}).get("youtube_id")
    db.update_video(video_id, status="published" if on_youtube else "ready")
    log.info("video %s finished: %s", video_id, "published" if on_youtube else "ready")
    return True


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="yt-kids: one video a day")
    parser.add_argument("--dry-run", action="store_true",
                        help="show the stages without touching the database")
    args = parser.parse_args()

    try:
        cfg = load_config()
    except ConfigError as e:
        log.error("config error: %s", e)
        return 2
    if args.dry_run:
        log.info("dry-run: stages would run in order: %s", " -> ".join(s[0] for s in STAGES))
        return 0

    account, token, _pixabay = credentials()
    db.init_db()
    existing = db.oldest_unfinished(MAX_ATTEMPTS)
    if existing:
        video_id = existing["id"]
        attempts = (existing.get("attempts") or 0) + 1
        log.info("carrying on with video %s (attempt %d of %d), status %s", video_id,
                 attempts, MAX_ATTEMPTS, existing["status"])
    else:
        video_id = db.create_video("pending")
        attempts = 1
        log.info("created video id=%s", video_id)
    db.update_video(video_id, attempts=attempts)

    ok = process_video(video_id, cfg, account, token)
    if not ok and attempts >= MAX_ATTEMPTS:
        log.error("video %s has now failed %d times and will not be retried; the next run "
                  "will start a new one", video_id, attempts)
        db.log_event(video_id, "run", "error", f"abandoned after {attempts} attempts")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
