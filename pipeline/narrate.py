"""Stage 3: speak every card as a short exchange, and measure how long each one runs.

The speech decides the card's length, not the other way round: the picture stays up until the
question has been asked, the child has had a second to think, and the answer and the fact have
been said. An intro and an outro bracket the whole video.

The ceiling from config is a target, not a cut. If the exchange runs past it the card runs
long and the log says so, because stopping the voice mid-sentence is worse than a card that
holds four seconds too long.
"""
from pathlib import Path

from core import tts
from core.logger import get_logger
from pipeline import talk

log = get_logger("narrate")

TAIL = 1.0          # how long the picture stays after the last word of a card


def card_length(speech_seconds, cfg):
    low = float(cfg.get("card_seconds_min", 12))
    high = float(cfg.get("card_seconds_max", 18))
    wanted = speech_seconds + TAIL
    return max(low, min(high, wanted)), wanted > high


def run(video_id, cfg, db, output_dir):
    out = Path(output_dir)
    audio_dir = out / "audio"
    cards = db.get_cards(video_id)
    if not cards:
        raise RuntimeError("there are no cards to narrate")
    video = db.get_video(video_id) or {}
    sounds_dir = out / "sounds"

    total, over = 0.0, []
    for card in cards:
        path = audio_dir / f"{card['idx']:02d}.mp3"
        sound = None
        if card["sound_id"]:
            found = sorted(sounds_dir.glob(f"{card['idx']:02d}.*"))
            sound = found[0] if found else None
        if not (path.exists() and path.stat().st_size > 1000):
            segments = talk.card_segments(card["idx"], card["subject"], card["fact"],
                                          sound, cfg)
            tts.build(segments, path, cfg, audio_dir / "_parts")
        speech = tts.duration(path)
        length, too_long = card_length(speech, cfg)
        if too_long:
            over.append(f"{card['subject']} {speech:.0f}s")
        db.update_card(card["id"], audio_path=str(path), duration_s=round(length, 3))
        total += length

    for name, segments in (("intro", talk.intro_segments(video.get("theme") or "animals", cfg)),
                           ("outro", talk.outro_segments(cfg))):
        path = audio_dir / f"_{name}.mp3"
        if not (path.exists() and path.stat().st_size > 1000):
            tts.build(segments, path, cfg, audio_dir / "_parts")
        total += tts.duration(path)

    minutes = total / 60
    log.info("%d cards narrated with an intro and an outro, %.1f minutes (%.1f s a card)",
             len(cards), minutes, (total / len(cards)))
    if over:
        log.warning("the talk runs past the %s s ceiling on %d card(s): %s",
                    cfg.get("card_seconds_max"), len(over), ", ".join(over))
    db.update_video(video_id, duration_s=round(total, 2))
    db.log_event(video_id, "narrate", "info",
                 f"{len(cards)} cards + intro/outro, {minutes:.1f} minutes"
                 + (f", {len(over)} over the ceiling" if over else ""))
    return True
