"""The narration: a name said on its own, then one short fact.

The shape of a card is the whole method. A two-year-old is being given a word, and a word
arrives only if there is room around it:

    <silence>  Whale.  <longer silence>  The blue whale is bigger than a bus.  <silence>

The gap after the name is the longest of the three on purpose - that is where the child
repeats the word, and if the sentence starts before they have finished, the word is gone.

So the parts are spoken separately and joined with measured silence, rather than written as
one sentence with commas and left to the voice's own phrasing. Edge's voices shorten a pause
when the sentence runs on, which is exactly the pause that must not be shortened.

The rate is slowed well below adult pace. Everything here is config, because the right numbers
are a matter for listening, not for argument.
"""
import asyncio
import subprocess
import tempfile
from pathlib import Path

import edge_tts

from core.logger import get_logger

log = get_logger("tts")

DEFAULT_VOICE = "en-US-AvaNeural"
DEFAULT_RATE = "-18%"


class TTSError(Exception):
    pass


async def _speak(text, out_path, voice, rate):
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(out_path))


def speak(text, out_path, voice=DEFAULT_VOICE, rate=DEFAULT_RATE):
    """One piece of speech to one file. Raises rather than writing an empty file."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(_speak(text, out_path, voice, rate))
    except Exception as e:                                       # noqa: BLE001
        raise TTSError(f"{voice} could not say {text[:40]!r}: {e}") from e
    if not out_path.exists() or out_path.stat().st_size < 500:
        raise TTSError(f"{voice} produced no audio for {text[:40]!r}")
    return out_path


def silence(seconds, out_path):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "anullsrc=channel_layout=mono:sample_rate=24000",
                    "-t", f"{seconds:.3f}", "-q:a", "9", str(out_path)],
                   capture_output=True, check=True, timeout=120)
    return out_path


def join(parts, out_path):
    """Concatenate audio files in order, re-encoding so the joins are clean."""
    out_path = Path(out_path)
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "parts.txt"
        listing.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in parts),
                           encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-ar", "24000", "-ac", "1", "-q:a", "4", str(out_path)],
                       capture_output=True, check=True, timeout=600)
    return out_path


def card_audio(name, fact, out_path, cfg, voice=None, work=None):
    """One card: silence, the name, a long gap, the fact, silence. Returns the path."""
    voice = voice or cfg.get("voice", DEFAULT_VOICE)
    rate = cfg.get("voice_rate", DEFAULT_RATE)
    before = cfg.get("pause_before_name_ms", 450) / 1000
    after = cfg.get("pause_after_name_ms", 900) / 1000
    between = cfg.get("pause_between_cards_ms", 700) / 1000

    work = Path(work or Path(out_path).parent / "_parts")
    work.mkdir(parents=True, exist_ok=True)
    stem = Path(out_path).stem
    parts = [
        silence(before, work / f"{stem}_a.mp3"),
        speak(name.rstrip(".") + ".", work / f"{stem}_name.mp3", voice, rate),
        silence(after, work / f"{stem}_b.mp3"),
        speak(fact, work / f"{stem}_fact.mp3", voice, rate),
        silence(between, work / f"{stem}_c.mp3"),
    ]
    return join(parts, out_path)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, timeout=120)
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise TTSError(f"ffprobe could not read a duration from {path}")
