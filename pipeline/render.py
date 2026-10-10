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
LABEL_FADE = 0.3                 # how long the name takes to arrive
LABEL_RISE = 40                  # and how far it slides up while it does
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
    # The name does not sit there for the whole card: it slides up and fades in over a
    # quarter of a second, roughly as it is spoken. A still label on a still frame is what
    # made the first cut look dead, and this is the cheapest thing that fixes it.
    overlay = (f"[1:v]format=rgba,fade=t=in:st=0:d={LABEL_FADE}:alpha=1[lab];"
               f"[v][lab]overlay=(W-w)/2:"
               f"'H-h-{LABEL_MARGIN}+max(0,({LABEL_RISE}-{LABEL_RISE}*t/{LABEL_FADE}))'")
    if card.get("clip_path"):
        # -stream_loop so a short clip fills a long card without being slowed down.
        args = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(card["clip_path"]),
                "-i", str(label), "-t", f"{seconds:.3f}", "-filter_complex",
                f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH}:{HEIGHT},eq=saturation=1.30:contrast=1.10,"
                f"zoompan=z='min(zoom+0.00035,1.08)':d=1:s={WIDTH}x{HEIGHT}:fps={FPS}[v];"
                f"{overlay}"]
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
    """The card's narration, padded to the card's length.

    The animal sound is NOT mixed here any more. It used to be laid under the voice at a
    fixed -6 dB, and since the source files are themselves -23 to -27 LUFS it arrived 8 to 12
    dB below the narration - which is to say, inaudible. It is now a segment of the narration
    itself, in its own gap, normalised to its own loudness; see core/tts.py. `sound_path` is
    kept only so an older call site does not break silently.
    """
    out_path = Path(out_path)
    _run(["ffmpeg", "-y", "-i", str(card["audio_path"]), "-af",
          f"apad=whole_dur={seconds:.3f}", "-t", f"{seconds:.3f}",
          "-ar", "44100", "-ac", "2", str(out_path)], TIMEOUT_PER_CARD)
    return out_path


# Short transitions, cycled by card so no two neighbours share one and the video does not
# settle into a rhythm. All are xfade modes, all cheap at this length - the cost is measured
# in scripts/transition_cost.py rather than guessed at, because an xfade chain over long
# clips is what took two hours in yt-factory. These cards are twenty seconds, not ten
# minutes, and the join happens once per pair rather than over a growing chain.
TRANSITIONS = ["slideleft", "wiperight", "fade", "slideup", "circleopen", "wipeleft",
               "dissolve", "slideright"]
TRANSITION_SECONDS = 0.4


def transition_for(index):
    return TRANSITIONS[index % len(TRANSITIONS)]


def join_with_transitions(paths, out_path, seconds=TRANSITION_SECONDS, timeout=3600):
    """Join cards with a short transition between each pair, in time linear in the cards.

    The obvious way - xfade the running video onto the next card, over and over - re-encodes
    everything accumulated so far at every step, so the work grows with the square of the card
    count. Measured on six eighteen-second cards: 372 seconds, against 0.5 for a plain concat.
    On twenty-five cards it would have been the two-hour disaster yt-factory had.

    So nothing long is ever re-encoded. Each card is cut into the part that plays on its own,
    the transitions are built from the half-second of tail and head either side of each join,
    and the result is stream-copied together. Each xfade is 0.4 seconds of video.

    Every card must have been rendered `seconds` longer than its slot, which card_video does,
    so the overlap is paid for out of that and the finished video is exactly as long as the
    narration. Card i's slot is its own piece plus the transition out of it.
    """
    paths = [Path(p) for p in paths]
    if len(paths) < 2:
        return paths[0] if paths else None
    out_path = Path(out_path)
    work = out_path.parent / "_joins"
    work.mkdir(parents=True, exist_ok=True)

    lengths = [probe_duration(p) for p in paths]
    encode = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
              "-r", str(FPS), "-an"]
    pieces = []
    for i, src in enumerate(paths):
        slot = lengths[i] - seconds
        begin = 0.0 if i == 0 else seconds
        length = (slot - seconds) if i == 0 else (
            lengths[i] - seconds if i == len(paths) - 1 else slot - seconds)
        piece = work / f"p{i:02d}.mp4"
        if not piece.exists():
            _run(["ffmpeg", "-y", "-ss", f"{begin:.3f}", "-i", str(src),
                  "-t", f"{max(length, 0.2):.3f}", *encode, str(piece)], timeout)
        pieces.append(piece)

        if i < len(paths) - 1:
            trans = work / f"t{i:02d}.mp4"
            if not trans.exists():
                tail_at = max(lengths[i] - seconds, 0.0)
                _run(["ffmpeg", "-y", "-ss", f"{tail_at:.3f}", "-t", f"{seconds:.3f}",
                      "-i", str(src), "-t", f"{seconds:.3f}", "-i", str(paths[i + 1]),
                      "-filter_complex",
                      f"[0:v][1:v]xfade=transition={transition_for(i)}"
                      f":duration={seconds}:offset=0",
                      *encode, str(trans)], timeout)
            pieces.append(trans)

    return concat(pieces, out_path, timeout)


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


def run(video_id, cfg, db, output_dir, sounds_dir=None, music=None,
        transitions=True):
    out = Path(output_dir)
    work = out / "cards"
    work.mkdir(parents=True, exist_ok=True)
    cards = db.get_cards(video_id)
    if not cards:
        raise RenderError("there are no cards to render")

    clips_dir, images_dir = out / "clips", out / "images"
    videos, audios = [], []
    for card in cards:
        slot = float(card["duration_s"] or cfg.get("card_seconds_min", 12))
        # One transition longer than the slot: the overlap is paid out of this, so the
        # finished video stays exactly as long as the narration.
        seconds = slot + (TRANSITION_SECONDS if transitions else 0.0)
        stem = f"{card['idx']:02d}"
        clip = clips_dir / f"{stem}_{card['subject'].replace(' ', '_')}.mp4"
        row = {**card, "clip_path": str(clip) if clip.exists() else None}
        vpath = work / f"{stem}_v.mp4"
        apath = work / f"{stem}_a.m4a"
        if not vpath.exists():
            card_video(row, seconds, vpath)
        if not apath.exists():
            card_audio(row, seconds, apath, cfg)
        videos.append(vpath)
        audios.append(apath)

    # The intro and outro are stills over the first and last card's picture, so the video
    # starts and ends on something rather than cutting straight in.
    intro, outro = out / "audio" / "_intro.mp3", out / "audio" / "_outro.mp3"
    if intro.exists():
        from core import tts as _tts
        bookend = {"subject": "", "clip_path": None,
                   "image_path": None, "audio_path": str(intro)}
        first = {**cards[0], "clip_path": str(clips_dir /
                 f"00_{cards[0]['subject'].replace(' ', '_')}.mp4")}
        for name, speech, source in (("intro", intro, first), ("outro", outro, first)):
            if not speech.exists():
                continue
            seconds = _tts.duration(speech) + 0.6
            vpath = work / f"_{name}_v.mp4"
            apath = work / f"_{name}_a.m4a"
            blank = {**source, "subject": ""}
            if not vpath.exists():
                card_video(blank, seconds, vpath)
            if not apath.exists():
                card_audio({"audio_path": str(speech)}, seconds, apath, cfg)
            if name == "intro":
                videos.insert(0, vpath)
                audios.insert(0, apath)
            else:
                videos.append(vpath)
                audios.append(apath)

    if transitions and len(videos) > 1:
        silent = join_with_transitions(videos, out / "_video.mp4")
    else:
        silent = concat(videos, out / "_video.mp4")
    track = concat(audios, out / "_audio.m4a")
    final = mux(silent, track, out / "final.mp4", cfg, music)

    length = probe_duration(final)
    log.info("rendered %d cards into %.1f minutes (%s)", len(cards), length / 60, final.name)
    db.update_video(video_id, video_path=str(final), duration_s=round(length, 2))
    db.log_event(video_id, "render", "info",
                 f"{len(cards)} cards, {length / 60:.1f} minutes")
    return True
