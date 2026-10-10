"""Stage 3: speak every card, and measure how long each one holds the screen.

The card's length is decided here rather than in the render, because it is the speech that
decides it: the picture has to stay up until the sentence has finished and the child has had
the gap after the name. The render is then told how long each card is, not the other way
round.

A card is held between config.card_seconds_min and card_seconds_max whatever the speech comes
to. Below the floor the child has not finished looking; above the ceiling - the brief's 18
seconds - a two-year-old has left. If the speech itself is longer than the ceiling the card
runs long and says so in the log, because cutting the voice off mid-sentence is worse.
"""
from pathlib import Path

from core import tts
from core.logger import get_logger

log = get_logger("narrate")


def card_length(speech_seconds, cfg):
    """How long the card holds the screen, given how long its narration is."""
    low = float(cfg.get("card_seconds_min", 12))
    high = float(cfg.get("card_seconds_max", 18))
    return max(low, min(high, speech_seconds + 1.5)), speech_seconds + 1.5 > high


def run(video_id, cfg, db, output_dir):
    out = Path(output_dir)
    audio_dir = out / "audio"
    cards = db.get_cards(video_id)
    if not cards:
        raise RuntimeError("there are no cards to narrate")

    total, over = 0.0, []
    for card in cards:
        path = audio_dir / f"{card['idx']:02d}.mp3"
        if not (path.exists() and path.stat().st_size > 1000):
            tts.card_audio(card["subject"].title(), card["fact"], path, cfg,
                           work=audio_dir / "_parts")
        speech = tts.duration(path)
        length, too_long = card_length(speech, cfg)
        if too_long:
            over.append(card["subject"])
        db.update_card(card["id"], audio_path=str(path), duration_s=round(length, 3))
        total += length

    minutes = total / 60
    log.info("%d cards narrated, %.1f minutes in all (%.1f s a card)",
             len(cards), minutes, total / len(cards))
    if over:
        log.warning("the speech runs past the %s s ceiling on %d card(s): %s",
                    cfg.get("card_seconds_max"), len(over), ", ".join(over))
    db.update_video(video_id, duration_s=round(total, 2))
    db.log_event(video_id, "narrate", "info",
                 f"{len(cards)} cards, {minutes:.1f} minutes"
                 + (f", {len(over)} over the ceiling" if over else ""))
    return True
