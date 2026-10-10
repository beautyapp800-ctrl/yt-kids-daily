"""The narration: a person talking to a child, not a list of names read out.

The first version was a announcer - name, gap, fact, next - at one pitch for seven minutes,
and a child does not listen to that. What a person actually does is ask, wait, and answer:

    Listen!   <the sound, loud, in silence>   Who makes that sound?
    <a second to think>   It's a cow!   A cow gives us milk.

Three things follow from that shape, and all three are the point:

The sound is a segment of its own, in a gap, at full level. It used to be mixed under the
voice with a fixed -6 dB, and the source files are themselves -23 to -27 LUFS, so it landed
8 to 12 dB below the narration and could not be heard at all. Mixing was the wrong idea: the
sound is the hook of the format, not atmosphere, so it is given its own silence and
normalised to a level of its own.

The pitch and rate move within a card. The name is slower and higher - that is how a person
offers a word to a child to repeat. A question rises. The answer is warm and quick. edge-tts
takes both parameters per utterance, which is checked rather than assumed: the same word at
+35Hz and at +0Hz comes back as different audio.

The gap after the name is still the longest silence in the card. That is where the child
says the word back, and it is the one thing that must not be shortened for pace.
"""
import asyncio
import subprocess
import tempfile
from pathlib import Path

import edge_tts

from core.logger import get_logger

log = get_logger("tts")

DEFAULT_VOICE = "en-US-JennyNeural"
DEFAULT_RATE = "-18%"

# How loud a downloaded animal sound is made before it goes in. Above the narration on
# purpose - measured, the voice sits near -21 LUFS, and this is the thing the child is
# supposed to notice.
SOUND_LUFS = -14.0
SOUND_MAX_SECONDS = 4.0


class TTSError(Exception):
    pass


def _ffmpeg(args, timeout=180):
    done = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, timeout=timeout)
    if done.returncode != 0:
        raise TTSError(f"ffmpeg: {done.stderr[-400:].decode('utf-8', 'replace')}")


def speak(text, out_path, voice=DEFAULT_VOICE, rate=DEFAULT_RATE, pitch="+0Hz"):
    """One utterance. Raises rather than leaving an empty file behind."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(out_path)))
    except Exception as e:                                       # noqa: BLE001
        raise TTSError(f"{voice} could not say {text[:40]!r}: {e}") from e
    if not out_path.exists() or out_path.stat().st_size < 500:
        raise TTSError(f"{voice} produced no audio for {text[:40]!r}")
    return out_path


def silence(seconds, out_path):
    _ffmpeg(["-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=24000",
             "-t", f"{seconds:.3f}", "-q:a", "9", str(out_path)])
    return out_path


def _window_start(src, want):
    """Where to start the clip inside a longer recording.

    Not at zero: a field recording of a penguin colony opens with the recordist settling
    down, and four seconds from the start is four seconds of wind. A tenth of the way in,
    capped, lands in the middle of the material without having to analyse it.
    """
    try:
        total = duration(src)
    except TTSError:
        return 0.0
    if total <= want * 1.5:
        return 0.0
    return min(total * 0.1, 20.0)


def normalise(src, out_path, lufs=SOUND_LUFS, max_seconds=SOUND_MAX_SECONDS):
    """Bring a downloaded sound up to a fixed loudness and trim it.

    Fixed loudness rather than a fixed gain: the files come from different people with
    different recording levels, and a gain that suits one leaves the next inaudible. Which
    is exactly what happened.
    """
    _ffmpeg(["-ss", f"{_window_start(src, max_seconds):.2f}", "-i", str(src),
             "-t", f"{max_seconds:.2f}",
             "-af", f"loudnorm=I={lufs}:TP=-1.5:LRA=11,afade=t=out:st={max_seconds - 0.3:.2f}:d=0.3",
             "-ar", "24000", "-ac", "1", "-q:a", "4", str(out_path)])
    return out_path


def join(parts, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "parts.txt"
        listing.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in parts),
                           encoding="utf-8")
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing),
                 "-ar", "24000", "-ac", "1", "-q:a", "4", str(out_path)], timeout=600)
    return out_path


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, timeout=120)
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise TTSError(f"ffprobe could not read a duration from {path}")


# How each piece of a card is said. Name: slower and higher, the way a word is offered to a
# child. Question: higher, so it rises. Answer: warm and a little quicker. Fact: normal.
VOICING = {
    "cue":      {"rate": "+14%", "pitch": "+40Hz"},
    "name":     {"rate": "-12%", "pitch": "+34Hz"},
    "question": {"rate": "+6%",  "pitch": "+38Hz"},
    "answer":   {"rate": "+12%", "pitch": "+30Hz"},
    "fact":     {"rate": "+8%",  "pitch": "+20Hz"},
    "plain":    {"rate": "+4%",  "pitch": "+12Hz"},
}


def say_part(text, kind, out_path, cfg, voice=None):
    voicing = VOICING.get(kind, VOICING["plain"])
    return speak(text, out_path, voice or cfg.get("voice", DEFAULT_VOICE),
                 voicing["rate"], voicing["pitch"])


def build(segments, out_path, cfg, work, voice=None):
    """Assemble a card from a list of segments, each a silence, an utterance or a sound file.

        ("gap", 0.9) | ("say", "Cow.", "name") | ("sound", Path(...))
    """
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    stem = Path(out_path).stem
    parts = []
    for i, segment in enumerate(segments):
        kind = segment[0]
        dst = work / f"{stem}_{i:02d}.mp3"
        if kind == "gap":
            parts.append(silence(float(segment[1]), dst))
        elif kind == "say":
            parts.append(say_part(segment[1], segment[2], dst, cfg, voice))
        elif kind == "sound":
            parts.append(normalise(segment[1], dst,
                                   float(cfg.get("sound_lufs", SOUND_LUFS)),
                                   float(cfg.get("sound_max_seconds", SOUND_MAX_SECONDS))))
        else:
            raise TTSError(f"unknown segment {kind!r}")
    return join(parts, out_path)
