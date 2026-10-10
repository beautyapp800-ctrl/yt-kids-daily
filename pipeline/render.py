"""Stage 4: one card at a time, then join them, then lay the sound over the top.

A card is a clip or a drawing, held for the length the narration needs, with the subject's
name across the bottom in big letters. Clips are looped and trimmed to that length rather than
sped up or slowed; a whale swimming at the wrong speed is a whale a child learns wrong.

Three things are mixed:

  the voice       full level, and everything else is set under it. A child who cannot make
                  out the word has not been taught anything.
  the real sound  played once, after the name, which is the point of the whole format. Level
                  from config.sound_gain_db, measured against the voice.
  the music       under both, from config.music_gain_db.

Each card is rendered on its own and the finished cards are concatenated. Joining short, already
encoded pieces is the one thing ffmpeg does quickly - yt-factory's xfade chain over 43 clips did
not finish in two hours, and the same mistake is not worth making twice.
"""
import json
import subprocess
from pathlib import Path

from core.logger import get_logger

log = get_logger("render")

WIDTH, HEIGHT, FPS = 1920, 1080, 30
FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Fredoka-Bold.ttf"
LABEL_SIZE = 110
LABEL_MARGIN = 70
STROKE = 10
TIMEOUT_PER_CARD = 600


class RenderError(Exception):
    pass


def _run(args, timeout):
    done = subprocess.run(args, capture_output=True, timeout=timeout)
    if done.returncode != 0:
        raise RenderError(f"{args[0]} failed: {done.stderr[-500:].decode('utf-8', 'replace')}")
    return done


def label_image(text, out_path, font=None, size=LABEL_SIZE, colour=(255, 255, 255)):
    """The subject's name as a transparent PNG, to be laid over the card.

    Drawn here rather than with ffmpeg's drawtext because Fredoka is a variable font and
    drawtext takes the default instance, which is Regular - a thin label over a photograph of
    a cow, which is the one thing it must not be. PIL can select the Bold instance.

    An outline, not a box. A box over a photograph hides the photograph, and the name has to
    sit ON the picture for a child to connect the two.
    """
    from PIL import Image, ImageDraw, ImageFont
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    face = ImageFont.truetype(str(font or FONT), size)
    try:
        face.set_variation_by_name("Bold")
    except Exception:                                            # noqa: BLE001
        pass                                                     # a static font is fine too
    shown = text.upper()
    pad = STROKE * 3
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    box = probe.textbbox((0, 0), shown, font=face, stroke_width=STROKE)
    img = Image.new("RGBA", (box[2] - box[0] + pad * 2, box[3] - box[1] + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((pad - box[0], pad - box[1]), shown, font=face, fill=colour,
                             stroke_width=STROKE, stroke_fill=(0, 0, 0, 230))
    img.save(out_path, "PNG")
    return out_path


def card_video(card, seconds, out_path, font=None):
    """One card as a silent video of exactly `seconds`."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    label = label_image(card["subject"], out_path.with_suffix(".label.png"), font)
    overlay = f"[v][1:v]overlay=(W-w)/2:H-h-{LABEL_MARGIN}"
    if card.get("clip_path"):
        # -stream_loop so a short clip fills a long card without being slowed down.
        args = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(card["clip_path"]),
                "-i", str(label), "-t", f"{seconds:.3f}", "-filter_complex",
                f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH}:{HEIGHT},eq=saturation=1.25:contrast=1.08[v];{overlay}"]
    else:
        # A still gets a slow push in, so the frame is not dead for fourteen seconds.
        zoom = (f"zoompan=z='min(zoom+0.0006,1.12)':d={int(seconds * FPS)}"
                f":s={WIDTH}x{HEIGHT}:fps={FPS}")
        args = ["ffmpeg", "-y", "-loop", "1", "-i", str(card["image_path"]),
                "-i", str(label), "-t", f"{seconds:.3f}", "-filter_complex",
                f"[0:v]scale={WIDTH * 2}:-1,{zoom},eq=saturation=1.15[v];{overlay}"]
    args += ["-an", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-pix_fmt", "yuv420p", str(out_path)]
    _run(args, TIMEOUT_PER_CARD)
    return out_path


def card_audio(card, seconds, out_path, cfg, sound_path=None):
    """The card's narration, with the real sound laid in after the name."""
    out_path = Path(out_path)
    voice = str(card["audio_path"])
    if not sound_path:
        _run(["ffmpeg", "-y", "-i", voice, "-af",
              f"apad=whole_dur={seconds:.3f}", "-t", f"{seconds:.3f}",
              "-ar", "44100", "-ac", "2", str(out_path)], TIMEOUT_PER_CARD)
        return out_path
    gain = float(cfg.get("sound_gain_db", -6))
    # Delayed to land in the gap after the name, where the child is already listening for it.
    delay = int(float(cfg.get("pause_before_name_ms", 450)) + 900)
    _run(["ffmpeg", "-y", "-i", voice, "-i", str(sound_path), "-filter_complex",
          f"[1:a]adelay={delay}|{delay},volume={gain}dB[s];"
          f"[0:a][s]amix=inputs=2:duration=first:normalize=0[a];"
          f"[a]apad=whole_dur={seconds:.3f}[out]",
          "-map", "[out]", "-t", f"{seconds:.3f}", "-ar", "44100", "-ac", "2",
          str(out_path)], TIMEOUT_PER_CARD)
    return out_path


def concat(paths, out_path, timeout=1800):
    out_path = Path(out_path)
    listing = out_path.parent / "_concat.txt"
    listing.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in paths),
                       encoding="utf-8")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
          "-c", "copy", str(out_path)], timeout)
    return out_path


def mux(video, audio, out_path, cfg, music=None, timeout=1800):
    """Video, narration-and-sounds, and the music bed under both."""
    out_path = Path(out_path)
    if music and Path(music).exists():
        gain = float(cfg.get("music_gain_db", -22))
        fade_out = float(cfg.get("fade_out_s", 3))
        args = ["ffmpeg", "-y", "-i", str(video), "-i", str(audio),
                "-stream_loop", "-1", "-i", str(music), "-filter_complex",
                f"[2:a]volume={gain}dB,afade=t=in:st=0:d={cfg.get('fade_in_s', 2)}[m];"
                f"[1:a][m]amix=inputs=2:duration=first:normalize=0,"
                f"afade=t=out:st=0:d={fade_out}:curve=tri[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(out_path)]
    else:
        args = ["ffmpeg", "-y", "-i", str(video), "-i", str(audio), "-map", "0:v", "-map",
                "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                str(out_path)]
    _run(args, timeout)
    return out_path


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, timeout=120)
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise RenderError(f"ffprobe could not read {path}")


def run(video_id, cfg, db, output_dir, sounds_dir=None, music=None):
    out = Path(output_dir)
    work = out / "cards"
    work.mkdir(parents=True, exist_ok=True)
    cards = db.get_cards(video_id)
    if not cards:
        raise RenderError("there are no cards to render")

    clips_dir, images_dir = out / "clips", out / "images"
    videos, audios = [], []
    for card in cards:
        seconds = float(card["duration_s"] or cfg.get("card_seconds_min", 12))
        stem = f"{card['idx']:02d}"
        clip = clips_dir / f"{stem}_{card['subject'].replace(' ', '_')}.mp4"
        row = {**card, "clip_path": str(clip) if clip.exists() else None}
        vpath = work / f"{stem}_v.mp4"
        apath = work / f"{stem}_a.m4a"
        if not vpath.exists():
            card_video(row, seconds, vpath)
        if not apath.exists():
            sound = None
            if sounds_dir and card["sound_id"]:
                found = list(Path(sounds_dir).glob(f"{stem}_*"))
                sound = found[0] if found else None
            card_audio(row, seconds, apath, cfg, sound)
        videos.append(vpath)
        audios.append(apath)

    silent = concat(videos, out / "_video.mp4")
    track = concat(audios, out / "_audio.m4a")
    final = mux(silent, track, out / "final.mp4", cfg, music)

    length = probe_duration(final)
    log.info("rendered %d cards into %.1f minutes (%s)", len(cards), length / 60, final.name)
    db.update_video(video_id, video_path=str(final), duration_s=round(length, 2))
    db.log_event(video_id, "render", "info",
                 f"{len(cards)} cards, {length / 60:.1f} minutes")
    return True
