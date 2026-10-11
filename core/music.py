"""The music bed: cheerful, light, and quiet enough that it never covers the lesson.

Two things are being protected. The narrator's voice, because a word a child cannot make out
has not been taught; and the animal sound, which is the whole hook of the format and sits
above the voice on purpose. Music that creeps up on either of them is worse than no music.

So the level is not a number somebody liked. The bed is normalised to a fixed loudness, and
the gap between it and the narration is measured on the finished mix - see pick_gain() - and
the build says what the gap came out as rather than assuming the filter did what was asked.

Licensing: the repository is public and the channel is monetised, so CC0 is preferred and
CC-BY is used with the credit carried into the description. NC and ND are refused, and SA is
refused because it would put the whole video under the same licence for the sake of a backing
track.
"""
import json
import subprocess
import urllib.request
from pathlib import Path

from core.logger import get_logger

log = get_logger("music")

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "music"
UA = "yt-kids/0.1 (educational videos for children)"

# How far under the narration the bed sits. Twelve decibels is the figure the measurement
# below is checked against: enough to hear, far enough down that the voice is never in doubt.
GAIN_UNDER_VOICE_DB = 12.0
FADE_IN = 1.5
FADE_OUT = 2.5


class MusicError(Exception):
    pass


def _ffmpeg(args, timeout=600):
    done = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, timeout=timeout)
    if done.returncode != 0:
        raise MusicError(done.stderr[-400:].decode("utf-8", "replace"))


def loudness(path):
    """Integrated loudness in LUFS, measured not guessed."""
    done = subprocess.run(["ffmpeg", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                          capture_output=True, timeout=900)
    text = done.stderr.decode("utf-8", "replace")
    for line in reversed(text.splitlines()):
        if line.strip().startswith("I:"):
            try:
                return float(line.split()[1])
            except (IndexError, ValueError):
                continue
    raise MusicError(f"could not read the loudness of {path}")


def tracks(folder=ASSETS):
    folder = Path(folder)
    return sorted(p for p in folder.glob("*.*") if p.suffix.lower() in (".mp3", ".ogg", ".wav",
                                                                        ".m4a", ".flac"))


def pick(video_id, folder=ASSETS):
    """One track, chosen by the video number so a rerun gives the same one."""
    found = tracks(folder)
    return found[int(video_id) % len(found)] if found else None


def credits(folder=ASSETS):
    """The attribution lines for whatever is in the folder, for the description."""
    meta = Path(folder) / "licences.json"
    if not meta.exists():
        return []
    out = []
    for row in json.loads(meta.read_text(encoding="utf-8")):
        if (row.get("licence") or "").lower() in ("cc0", "pdm"):
            continue
        out.append(f"{row['title']} by {row.get('creator') or 'unknown'} "
                   f"({row.get('page')}), licensed CC BY {row.get('version') or ''}".strip())
    return out


def fetch(url, dst):
    dst = Path(dst)
    if dst.exists() and dst.stat().st_size > 10000:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as resp:
        dst.write_bytes(resp.read(40 * 1024 * 1024))
    if dst.stat().st_size < 10000:
        raise MusicError(f"{url} returned {dst.stat().st_size} bytes")
    return dst


def pick_gain(track, narration, under_db=GAIN_UNDER_VOICE_DB):
    """The gain that puts the bed `under_db` below the narration, from both measurements."""
    return round(loudness(narration) - under_db - loudness(track), 1)


def bed(track, seconds, out_path, gain_db, fade_in=FADE_IN, fade_out=FADE_OUT):
    """The track, looped to length, faded at both ends, at the gain asked for."""
    out_path = Path(out_path)
    start_out = max(seconds - fade_out, 0.1)
    # -vn because the track carries embedded album art, which ffmpeg treats as a video
    # stream; without it the filter graph builds a video thread that fails on the still and
    # the whole bed comes out as "Invalid argument" with nothing written.
    _ffmpeg(["-stream_loop", "-1", "-i", str(track), "-t", f"{seconds:.3f}", "-vn",
             "-af", f"volume={gain_db}dB,afade=t=in:st=0:d={fade_in},"
                    f"afade=t=out:st={start_out:.2f}:d={fade_out}",
             "-ar", "44100", "-ac", "2", str(out_path)])
    return out_path
