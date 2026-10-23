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
import tempfile
from pathlib import Path

from core.logger import get_logger
from core import music as music_lib
from pipeline import grid

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
        # -stream_loop so a short clip fills a long card without being slowed down. There
        # used to be a zoompan push-in here; measured on a still frame it never moved at all -
        # with d=1 on a video input zoompan starts over on every frame - so it is gone.
        args = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(card["clip_path"]),
                "-loop", "1", "-i", str(label), "-t", f"{seconds:.3f}", "-filter_complex",
                f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH}:{HEIGHT},eq=saturation=1.30:contrast=1.10[v];"
                f"{overlay}"]
    else:
        # A still gets a slow push in, so the frame is not dead for fourteen seconds.
        zoom = (f"zoompan=z='min(zoom+0.0006,1.12)':d={int(seconds * FPS)}"
                f":s={WIDTH}x{HEIGHT}:fps={FPS}")
        args = ["ffmpeg", "-y", "-loop", "1", "-i", str(card["image_path"]),
                "-loop", "1", "-i", str(label), "-t", f"{seconds:.3f}", "-filter_complex",
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
    """Video, narration-and-sounds, and the music bed under both.

    `music` arrives already normalised, faded and at the gain the measurement chose, so
    nothing is applied to it here - a second gain in this function is how the measured level
    stops being the level.
    """
    out_path = Path(out_path)
    if music and Path(music).exists():
        args = ["ffmpeg", "-y", "-i", str(video), "-i", str(audio), "-i", str(music),
                "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=first:normalize=0[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(out_path)]
    else:
        args = ["ffmpeg", "-y", "-i", str(video), "-i", str(audio), "-map", "0:v", "-map",
                "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                str(out_path)]
    _run(args, timeout)
    check_sound_runs_the_whole_way(out_path)
    return out_path


# How much shorter the sound may be than the picture before the file is refused. A frame or
# two is the normal rounding between a video stream and an AAC stream; a second is not.
SOUND_SHORTFALL = 0.5


def check_sound_runs_the_whole_way(path):
    """Refuse a file whose audio stops before its picture does.

    A muxer does not complain about this and neither does a player: it shows the pictures to
    the end and plays silence. It was found by ear, in a sample where the audio stream was two
    minutes against six and a half of video, and by ear it reads as "the music stopped" rather
    than as a broken file - which is exactly why it has to be measured here instead of watched
    for. Stream durations, not the container's, because the container reports the longest one.
    """
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=duration", "-of", "default=nw=1:nk=1",
                          str(path)], capture_output=True, text=True, timeout=120)
    audio = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                            "-show_entries", "stream=duration", "-of", "default=nw=1:nk=1",
                            str(path)], capture_output=True, text=True, timeout=120)
    try:
        video_seconds = float(out.stdout.strip())
        audio_seconds = float(audio.stdout.strip())
    except ValueError:
        raise RenderError(f"{Path(path).name} has no video or no audio stream to measure")
    if video_seconds - audio_seconds > SOUND_SHORTFALL:
        raise RenderError(
            f"{Path(path).name} would play {video_seconds - audio_seconds:.1f} s of pictures "
            f"in silence: the audio stream is {audio_seconds:.1f} s against "
            f"{video_seconds:.1f} s of video")
    return video_seconds, audio_seconds


# How much louder the finished mix must be than the narration alone, in the moments where the
# narration is quiet. The bed sits 12 dB under the voice, so in a gap it is the only thing
# there and the difference is large; 3 dB is well clear of codec noise and well under what a
# real bed gives.
MUSIC_IN_GAPS_DB = 3.0


def _levels_per_second(path, rate=8000):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1",
                          "-ar", str(rate), "-f", "s16le", "-"],
                         capture_output=True, timeout=600).stdout
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    seconds = len(samples) // rate
    if seconds < 2:
        return np.zeros(0)
    block = samples[:seconds * rate].reshape(seconds, rate)
    return 20 * np.log10(np.maximum(np.sqrt((block ** 2).mean(axis=1)), 1e-7))


def check_music_is_audible(narration, final, want_db=MUSIC_IN_GAPS_DB):
    """Prove the bed is really in the mix, by comparing the two files second by second.

    A log line saying a bed was built is not evidence that it reached the viewer: the filter
    could drop it, the gain could be wrong, the mux could take the wrong input. So the quietest
    tenth of the narration - the gaps between sentences, where the bed is the only thing
    playing - is measured in both files. In the finished mix those seconds have to be clearly
    louder than they are in the narration alone, across the whole video and not just at the
    start.
    """
    import numpy as np
    speech, mixed = _levels_per_second(narration), _levels_per_second(final)
    span = min(len(speech), len(mixed))
    if span < 10:
        raise RenderError("the mix is too short to check the music in")
    speech, mixed = speech[:span], mixed[:span]
    quiet = np.argsort(speech)[:max(span // 10, 5)]
    lift = float(np.median(mixed[quiet] - speech[quiet]))
    # And in both halves, so a bed that stops in the middle is caught as well.
    halves = [float(np.median(mixed[q] - speech[q]))
              for q in (quiet[quiet < span // 2], quiet[quiet >= span // 2]) if len(q) >= 2]
    if lift < want_db or any(h < want_db for h in halves):
        raise RenderError(
            f"the music is not in the mix: in the quietest seconds it lifts the sound by "
            f"{lift:.1f} dB (halves: {', '.join(f'{h:.1f}' for h in halves)}), and a bed "
            f"{MUSIC_IN_GAPS_DB:.0f} dB under the voice should give far more")
    return {"lift_db": round(lift, 1), "halves_db": [round(h, 1) for h in halves]}


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, timeout=120)
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise RenderError(f"ffprobe could not read {path}")



# --- the board ---------------------------------------------------------------------------

BOARD_OPEN = 2.2         # how long the whole board is held at the start
BOARD_HOLD = 0.5         # and between cards, after a tick lands
ZOOM_IN = 0.6
ZOOM_OUT = 0.5


def _still(clip_path, dst, at=2.0):
    """One bright frame from a clip, for its cell on the board."""
    dst = Path(dst)
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-ss", f"{at}", "-i", str(clip_path), "-frames:v", "1",
          "-vf", "scale=640:360,eq=saturation=1.35:contrast=1.08", str(dst)], 300)
    return dst


def still_for(card, clips_dir, images_dir, work):
    """The picture that stands for this card on the board."""
    stem = f"{card['idx']:02d}"
    clip = Path(clips_dir) / f"{stem}_{card['subject'].replace(' ', '_')}.mp4"
    dst = Path(work) / f"still_{stem}.jpg"
    if clip.exists():
        return _still(clip, dst)
    if card.get("image_path"):
        if not dst.exists():
            _run(["ffmpeg", "-y", "-i", str(card["image_path"]),
                  "-vf", "scale=640:360,eq=saturation=1.35", str(dst)], 300)
        return dst
    raise RenderError(f"card {card['idx']} has neither a clip nor a picture")


def _still_clip(image, seconds, out_path, vf=None):
    """A still held for `seconds`, optionally through a filter."""
    out_path = Path(out_path)
    if out_path.exists():
        return out_path
    args = ["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-t", f"{seconds:.3f}"]
    args += ["-vf", vf or f"scale={WIDTH}:{HEIGHT}"]
    args += ["-an", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-pix_fmt", "yuv420p", str(out_path)]
    _run(args, TIMEOUT_PER_CARD)
    return out_path


def _zoom_clip(board_image, box, seconds, out_path, into=True):
    """The flight between the board and one cell, drawn frame by frame and piped to ffmpeg.

    Raw frames over a pipe rather than a folder of PNGs: a 0.6 s flight is 18 frames of
    1920x1080, and writing then re-reading them would cost more than making them.
    """
    out_path = Path(out_path)
    if out_path.exists():
        return out_path
    frames = max(int(round(seconds * FPS)), 2)
    args = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-loglevel", "error", str(out_path)]
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=errors)
        try:
            for frame in grid.zoom_frames(board_image, box, frames, into):
                proc.stdin.write(frame)
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass
        if proc.wait(timeout=TIMEOUT_PER_CARD) != 0:
            errors.seek(0)
            raise RenderError(f"ffmpeg failed on the flight into {box}: "
                              f"{errors.read()[-500:].decode('utf-8', 'replace')}")
    return out_path


def board_pieces(cards, stills, labels, work, cfg):
    """[(video, seconds, kind, card_index)] - the board moments around every card.

    The board is what makes the video a game rather than a list: it opens on every subject at
    once, each card is a cell growing to fill the screen, and the cell comes back with a tick
    on it. A child who cannot count can still see the board filling up.
    """
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    _c, _r, _cw, _ch, boxes = grid.layout(len(cards))
    out = []

    opening = grid.board(stills, set(), work / "board_open.jpg", None, labels)
    out.append((_still_clip(opening, BOARD_OPEN, work / "open.mp4"), BOARD_OPEN, "board", -1))

    for i, _card in enumerate(cards):
        before = grid.board(stills, set(range(i)), work / f"board_{i:02d}_in.jpg", i, labels)
        out.append((_zoom_clip(before, boxes[i], ZOOM_IN, work / f"zin_{i:02d}.mp4",
                               into=True), ZOOM_IN, "zoom_in", i))
        out.append((None, None, "card", i))
        after = grid.board(stills, set(range(i + 1)), work / f"board_{i:02d}_out.jpg",
                           None, labels)
        out.append((_zoom_clip(after, boxes[i], ZOOM_OUT, work / f"zout_{i:02d}.mp4",
                               into=False), ZOOM_OUT, "zoom_out", i))
        if i < len(cards) - 1:
            out.append((_still_clip(after, BOARD_HOLD, work / f"hold_{i:02d}.mp4"),
                        BOARD_HOLD, "board", i))
    return out


def silent_audio(seconds, out_path):
    out_path = Path(out_path)
    if out_path.exists():
        return out_path
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i",
          "anullsrc=channel_layout=stereo:sample_rate=44100",
          "-t", f"{seconds:.3f}", "-c:a", "aac", "-b:a", "192k", str(out_path)], 300)
    return out_path


def run(video_id, cfg, db, output_dir, sounds_dir=None, music=None, board=True):
    """Build final.mp4.

    With `board` on, the video is played on the grid: it opens on every subject at once, each
    card is a cell growing to fill the screen, and the cell comes back ticked. The zooms are
    the transitions, so the xfade joins are not used as well - two kinds of transition at the
    same join is one too many, and the zoom is the one that carries meaning.
    """
    out = Path(output_dir)
    work = out / "cards"
    work.mkdir(parents=True, exist_ok=True)
    cards = db.get_cards(video_id)
    if not cards:
        raise RenderError("there are no cards to render")
    clips_dir, images_dir = out / "clips", out / "images"

    # The cards themselves.
    card_video_for, card_audio_for = {}, {}
    for card in cards:
        slot = float(card["duration_s"] or cfg.get("card_seconds_min", 12))
        seconds = slot if board else slot + TRANSITION_SECONDS
        stem = f"{card['idx']:02d}"
        clip = clips_dir / f"{stem}_{card['subject'].replace(' ', '_')}.mp4"
        row = {**card, "clip_path": str(clip) if clip.exists() else None}
        vpath, apath = work / f"{stem}_v.mp4", work / f"{stem}_a.m4a"
        if not vpath.exists():
            card_video(row, seconds, vpath)
        if not apath.exists():
            card_audio(row, seconds, apath, cfg)
        card_video_for[card["idx"]] = vpath
        card_audio_for[card["idx"]] = apath

    videos, audios = [], []

    def add(video, audio):
        videos.append(video)
        audios.append(audio)

    # The opening is spoken over the whole board, so the child is looking at what is coming
    # while being told what it is.
    intro, outro = out / "audio" / "_intro.mp3", out / "audio" / "_outro.mp3"
    if board:
        from core import tts as _tts
        stills = [still_for(c, clips_dir, images_dir, work) for c in cards]
        labels = [c["subject"] for c in cards]
        pieces = board_pieces(cards, stills, labels, work / "board", cfg)

        opening = pieces[0]
        if intro.exists():
            speech = _tts.duration(intro) + 0.4
            open_board = grid.board(stills, set(), work / "board" / "board_open.jpg",
                                    None, labels)
            vpath = work / "board" / "open_long.mp4"
            if not vpath.exists():
                _still_clip(open_board, speech, vpath)
            apath = work / "_intro_a.m4a"
            if not apath.exists():
                card_audio({"audio_path": str(intro)}, speech, apath, cfg)
            add(vpath, apath)
        else:
            add(opening[0], silent_audio(opening[1], work / "board" / "open_a.m4a"))

        for video, seconds, kind, index in pieces[1:]:
            if kind == "card":
                add(card_video_for[cards[index]["idx"]], card_audio_for[cards[index]["idx"]])
            else:
                add(video, silent_audio(seconds, work / "board" / f"{Path(video).stem}_a.m4a"))

        if outro.exists():
            speech = _tts.duration(outro) + 0.5
            done_board = grid.board(stills, set(range(len(cards))),
                                    work / "board" / "board_done.jpg", None, labels)
            vpath = work / "board" / "done_long.mp4"
            if not vpath.exists():
                _still_clip(done_board, speech, vpath)
            apath = work / "_outro_a.m4a"
            if not apath.exists():
                card_audio({"audio_path": str(outro)}, speech, apath, cfg)
            add(vpath, apath)
    else:
        for card in cards:
            add(card_video_for[card["idx"]], card_audio_for[card["idx"]])

    if board:
        silent = concat(videos, out / "_video.mp4")
    else:
        silent = (join_with_transitions(videos, out / "_video.mp4") if len(videos) > 1
                  else concat(videos, out / "_video.mp4"))
    track = concat(audios, out / "_audio.m4a")

    # The music level is measured, not chosen. Both the narration and the track are read in
    # LUFS and the gain is whatever puts the bed the configured number of decibels under the
    # voice; the gap is then read back off the finished mix and logged, because a filter that
    # silently does something else is exactly how a bed ends up on top of the lesson.
    # Not optional. The first version skipped the bed whenever there was no track to use and
    # logged nothing at all, so a blanket *.mp3 in .gitignore left the runner with an empty
    # folder and video 1 was published silent - the one fault of this whole build that reached
    # a viewer. A missing bed is now a failed render: the video is rebuilt in twelve minutes,
    # and a published video cannot be quietly replaced.
    chosen = music or music_lib.pick(video_id)
    if not chosen:
        raise RenderError(
            f"there is no music to score this with: {music_lib.ASSETS} has no audio file. "
            "Check that the tracks are committed - .gitignore once excluded them.")
    if not Path(chosen).exists():
        raise RenderError(f"the music track {chosen} is named but not on disk")
    under = float(cfg.get("music_under_voice_db", music_lib.GAIN_UNDER_VOICE_DB))
    gain = music_lib.pick_gain(chosen, track, under)
    bed = music_lib.bed(chosen, probe_duration(silent), out / "_music.m4a", gain)
    log.info("music %s at %+.1f dB (%.1f LUFS track, %.1f LUFS narration, "
             "wanted %.0f dB under)", Path(chosen).name, gain,
             music_lib.loudness(chosen), music_lib.loudness(track), under)

    final = mux(silent, track, out / "final.mp4", cfg, bed)
    heard = check_music_is_audible(track, final)
    log.info("music measured in the finished mix: it lifts the quietest seconds by %.1f dB "
             "(%s per half)", heard["lift_db"],
             ", ".join(f"{h:.1f}" for h in heard["halves_db"]))

    length = probe_duration(final)
    log.info("rendered %d cards into %.1f minutes (%s)%s", len(cards), length / 60,
             final.name, " on the board" if board else "")
    db.update_video(video_id, video_path=str(final), duration_s=round(length, 2))
    db.log_event(video_id, "render", "info",
                 f"{len(cards)} cards, {length / 60:.1f} minutes"
                 + (", played on the board" if board else ""))
    return True
