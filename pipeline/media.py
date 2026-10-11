"""Stage 2: get a picture for every card - download the footage, draw the rest.

Both are expensive and both are resumable: a file already on disk is not fetched or drawn
again, so a run that dies at the render does not pay twice. That matters more here than in
yt-factory because a clip is tens of megabytes, not a 96-Neuron image.

The drawn cards use the bright style in config.image_style. The bans that apply to generated
pictures elsewhere in the project apply here too - no hands, no faces, no lettering - but for
a different reason: a child does not need a cartoon hand holding the banana, and generated
lettering is garbled whatever the audience.
"""
import time
import urllib.error
import urllib.request
from pathlib import Path

from core.logger import get_logger

log = get_logger("media")

UA = "yt-kids/0.1 (educational videos for children)"
DOWNLOAD_TIMEOUT = 300
MAX_CLIP_BYTES = 120 * 1024 * 1024


class MediaError(Exception):
    pass


DOWNLOAD_ATTEMPTS = 4


def download(url, dst, timeout=DOWNLOAD_TIMEOUT, attempts=DOWNLOAD_ATTEMPTS):
    """Fetch a clip. Returns the path; raises MediaError on anything that is not a video.

    Retried, because the first version gave up on the first error and the first error was a
    DNS blip: the seahorse card lost its footage to one failed lookup and fell through to
    being drawn. A clip that is in the catalogue has been checked by a model and is worth
    more than a drawing, so it is worth asking again for.
    """
    dst = Path(dst)
    if dst.exists() and dst.stat().st_size > 10000:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                kind = resp.headers.get("Content-Type", "")
                if "video" not in kind and "octet-stream" not in kind:
                    raise MediaError(f"{url} returned {kind!r}, not a video")
                data = resp.read(MAX_CLIP_BYTES + 1)
            break
        except MediaError:
            raise
        except urllib.error.URLError as e:
            last = e.reason
        except Exception as e:                                   # noqa: BLE001
            last = str(e)[:120]
        if attempt == attempts:
            raise MediaError(f"{url}: {last} (after {attempts} attempts)")
        wait = min(2 ** attempt, 15)
        log.info("clip download failed (%d/%d), waiting %ds: %s",
                 attempt, attempts, wait, str(last)[:70])
        time.sleep(wait)
    if len(data) > MAX_CLIP_BYTES:
        raise MediaError(f"{url} is over {MAX_CLIP_BYTES // (1024 * 1024)} MB")
    if len(data) < 10000:
        raise MediaError(f"{url} returned {len(data)} bytes")
    dst.write_bytes(data)
    return dst


def draw_prompt(subject, style):
    """The prompt for a card that has no footage.

    One thing, big, in the middle, on a plain background - which is the opposite of the
    thumbnail composition in yt-factory and right for the same reason: here the subject IS
    the lesson, and anything else in the frame is something else for the child to look at.
    """
    return (f"{style}, a single {subject}, large and centred, filling most of the frame, "
            f"seen from the side, plain simple background, nothing else in the picture")


def draw(subject, dst, cfg, account, token, images_module=None):
    """Draw one card. Returns the path, or None if the generator would not."""
    dst = Path(dst)
    if dst.exists() and dst.stat().st_size > 1000:
        return dst
    if images_module is None:
        from core import images as images_module
    prompt = draw_prompt(subject, (cfg.get("image_style") or "").strip())
    try:
        images_module.draw(prompt, dst, account, token, cfg)
    except Exception as e:                                       # noqa: BLE001
        log.warning("could not draw %s: %s", subject, str(e)[:120])
        return None
    return dst if dst.exists() else None


def fetch_sound(card, sounds_dir):
    """Download the card's sound, if it has one. Returns the path or None.

    This was missing: plan.py recorded the sound's id and licence and nothing ever fetched
    the file, so the first rendered video was voice-only - the hook the whole format is built
    on, silently absent. The database said it was there.
    """
    if not card.get("sound_id") or not card.get("sound_url"):
        return None
    dst = Path(sounds_dir) / f"{card['idx']:02d}{Path(card['sound_url']).suffix or '.mp3'}"
    if dst.exists() and dst.stat().st_size > 500:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(card["sound_url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read(20 * 1024 * 1024)
    except Exception as e:                                       # noqa: BLE001
        log.warning("card %d (%s): sound would not download: %s", card["idx"],
                    card["subject"], str(e)[:90])
        return None
    if len(data) < 500:
        return None
    dst.write_bytes(data)
    return dst


def run(video_id, cfg, account, token, db, output_dir, images_module=None):
    """Fill in every card's media. Returns True when every card has something to show."""
    out = Path(output_dir)
    clips_dir, images_dir = out / "clips", out / "images"
    sounds_dir = out / "sounds"
    cards = db.get_cards(video_id)
    missing = []
    for card in cards:
        if card["video_source"] == "stock" and card["clip_url"]:
            dst = clips_dir / f"{card['idx']:02d}_{card['subject'].replace(' ', '_')}.mp4"
            try:
                download(card["clip_url"], dst)
                db.update_card(card["id"], image_path=None)
                continue
            except MediaError as e:
                # Not fatal: the card falls back to a drawing, which is what the drawn
                # cards do anyway. A video short one card is worse than a drawn card.
                log.warning("card %d (%s): %s; drawing it instead", card["idx"],
                            card["subject"], str(e)[:100])
                db.update_card(card["id"], video_source="drawn")
                card = {**card, "video_source": "drawn"}
        if card["video_source"] == "drawn":
            dst = images_dir / f"{card['idx']:02d}_{card['subject'].replace(' ', '_')}.jpg"
            path = draw(card["subject"], dst, cfg, account, token, images_module)
            if path:
                db.update_card(card["id"], image_path=str(path))
            else:
                missing.append(card["subject"])

    if missing:
        raise MediaError(f"no picture at all for: {', '.join(missing)}")

    with_sound = 0
    for card in db.get_cards(video_id):
        if fetch_sound(card, sounds_dir):
            with_sound += 1
        elif card["sound_id"]:
            # The record said there was a sound and there is not. Clear it, so nothing
            # downstream believes the database over the disk.
            db.update_card(card["id"], sound_id=None, sound_licence=None,
                           sound_attribution=None)

    filmed = sum(1 for c in db.get_cards(video_id) if c["video_source"] == "stock")
    log.info("media ready: %d filmed, %d drawn, %d with their own sound",
             filmed, len(cards) - filmed, with_sound)
    db.log_event(video_id, "media", "info",
                 f"{filmed} clips, {len(cards) - filmed} drawn, {with_sound} sounds")
    return True
