"""The "Guess who?" half of the video: the same subjects again, hidden, then revealed.

After the learning half, a full-screen "Guess who?" card, then one turn per subject in a
shuffled order. A turn, at its usual length of twelve seconds:

    0.0-0.5   in from the brand colour
    0.5-2.5   the riddle on screen; the real sound, if the thing makes one
    2.5-4.0   the question ("Who is this?" / "Can you guess?" / "Who makes this sound?" ...)
    4.0-7.0   3, 2, 1 - a second each, a quiet tick on each
    7.0-7.3   the reveal: whoosh or pop, the picture opens to the full frame, confetti
    7.3-9.5   "Yes! It's a lion!", with the name large on screen
    9.5-11.5  the real sound again, or the picture held
    11.5-12   out to the brand colour

Times are minimums. A question that takes longer than its window pushes the countdown back
rather than talking over it, and the hold at the end is what the length balancer adjusts.

The riddle is a frozen frame of the clip, cut down to a detail of it ("guess by a piece"). At
the reveal the camera pulls back over that same frozen frame - the affine flight the board
uses, exact and eased, so nothing steps or swims - and then the clip starts playing from that
very frame. Freezing it means a walking zebra cannot wander out of its own detail during the
countdown, and the moment the picture comes alive is part of the reveal. No silhouette: the
cut-outs were measured and gave one eye of a shark. Where no detail is worth showing - open
water, sky, a blur of leaves - the riddle is the whole frame, heavily blurred, and the blur is
taken off at once.
"""
import math
import random
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from core.logger import get_logger
from pipeline import grid

log = get_logger("game")

WIDTH, HEIGHT, FPS = 1920, 1080, 30
BRAND = (46, 196, 255)            # the board's own sky blue: every turn starts and ends on it

# The turn, in seconds from its start. Minimums; see the module docstring.
T_IN = 0.5
T_RIDDLE_SOUND = 0.5
T_QUESTION = 2.5
T_COUNTDOWN = 4.0
COUNT = 3
T_REVEAL_AFTER = 0.0              # the reveal follows the last number directly
REVEAL_MOVE = 0.6                 # the pull-back, eased
REVEAL_FREEZE = 0.4               # the full frame held, with confetti, before it plays
T_ANSWER_AFTER_REVEAL = 0.3
T_SECOND_SOUND_AFTER_REVEAL = 2.5
OUT = 0.5
BASE_HOLD = 0.0                   # what the balancer adds to or takes from, per turn
SOUND_SECONDS = 2.0               # each playing of the real sound

QUESTIONS = ["Who is this?", "Can you guess?", "Who makes this sound?", "Do you know this one?"]
SOUND_QUESTION = "Who makes this sound?"
ANSWERS = ["Yes! It's {a} {name}!", "That's right, {a} {name}!", "Great job! {A} {name}!"]
GUESS_LINE = "Now let's play a game! Can you guess who it is?"

PIECE_ZOOM = 2.4                  # how far into the frame the detail is cut
PIECE_MIN_DETAIL = 0.03           # below this the best detail is too plain to guess from
SMALL_SUBJECT = 0.05              # catalogue-measured share of the frame below which it blurs
BLUR_RADIUS = 46


# --- what is said ------------------------------------------------------------------------

def _article(name):
    return "an" if name[:1].lower() in "aeiou" else "a"


def question_for(turn, has_sound):
    """Rotates, and "who makes this sound?" only where a sound was actually played."""
    options = QUESTIONS if has_sound else [q for q in QUESTIONS if q != SOUND_QUESTION]
    return options[turn % len(options)]


def answer_for(turn, subject):
    name = subject.strip().lower()
    a = _article(name)
    return ANSWERS[turn % len(ANSWERS)].format(a=a, A=a.capitalize(), name=name)


def order(cards, video_id):
    """The game's order: shuffled, the same on every rerun of this video, and never opening
    on the subject the learning half ended with - that one is still on the child's mind."""
    rng = random.Random(int(video_id) * 104729)
    shuffled = list(cards)
    for _ in range(20):
        rng.shuffle(shuffled)
        if len(shuffled) < 2 or shuffled[0]["idx"] != cards[-1]["idx"]:
            break
    return shuffled


# --- the timeline ------------------------------------------------------------------------

def timeline(question_seconds, answer_seconds, has_sound, hold=BASE_HOLD):
    """{name: seconds from the turn's start} for one turn, and its total length.

    Built forward from the minimums so a long line pushes what follows instead of overlapping
    it, then rounded to whole frames so picture and sound stay together across fifteen turns.
    """
    t = {"riddle": T_IN, "sound1": T_RIDDLE_SOUND if has_sound else None}
    t["question"] = T_QUESTION
    t["countdown"] = max(T_COUNTDOWN, T_QUESTION + question_seconds + 0.15)
    t["reveal"] = t["countdown"] + COUNT + T_REVEAL_AFTER
    t["frozen_until"] = t["reveal"] + REVEAL_MOVE + REVEAL_FREEZE
    t["answer"] = t["reveal"] + T_ANSWER_AFTER_REVEAL
    answer_end = t["answer"] + answer_seconds
    if has_sound:
        t["sound2"] = max(t["reveal"] + T_SECOND_SOUND_AFTER_REVEAL, answer_end + 0.2)
        settled = t["sound2"] + SOUND_SECONDS
    else:
        t["sound2"] = None
        settled = max(t["reveal"] + T_SECOND_SOUND_AFTER_REVEAL + SOUND_SECONDS,
                      answer_end + 0.8)
    end = max(settled + hold, t["frozen_until"] + 1.0) + OUT
    t["end"] = round(end * FPS) / FPS
    t["out"] = t["end"] - OUT
    return t


# --- the riddle --------------------------------------------------------------------------

def _detail_map(img):
    """(texture, colour) maps of the frame on a coarse grid.

    Texture is the gradient of brightness and colour together; colour is how saturated a
    spot is. A first version also asked how far each spot's colour stood off the frame's own
    edge, and that sank every close-up - when a peacock's fan fills the frame, the edge IS the
    fan, so nothing looked apart and the peacock, the elephant, the lion and the pig all went
    to blur though each has an obvious detail.
    """
    small = np.asarray(img.convert("RGB").resize((192, 108), Image.BILINEAR),
                       dtype=np.float32) / 255.0
    grads = []
    for c in range(3):
        gy, gx = np.gradient(small[..., c])
        grads.append(np.sqrt(gx ** 2 + gy ** 2))
    texture = np.mean(grads, axis=0)
    hi, lo = small.max(axis=2), small.min(axis=2)
    colour = np.where(hi > 0, (hi - lo) / np.maximum(hi, 1e-6), 0) * hi
    return texture, colour


def choose_piece(still, zoom=PIECE_ZOOM, floor=PIECE_MIN_DETAIL, subject_area=None):
    """(box, score) - the detail of `still` to show as the riddle, or (None, score) for blur.

    The box is 16:9 and 1/zoom of the frame, favoured towards the middle because stock footage
    frames its subject there. `subject_area` is what the catalogue measured, once, of how much
    of this clip's frame the subject fills: below SMALL_SUBJECT a piece is a piece of the
    background, so it is the blur, whatever the texture says.
    """
    texture, colour = _detail_map(still)
    h, w = texture.shape
    bw, bh = int(round(w / zoom)), int(round(h / zoom))
    combined = texture * (0.5 + colour)
    integral = np.pad(combined.cumsum(axis=0).cumsum(axis=1), ((1, 0), (1, 0)))
    best, best_at = -1.0, None
    for y in range(0, h - bh + 1, 2):
        for x in range(0, w - bw + 1, 2):
            total = (integral[y + bh, x + bw] - integral[y, x + bw]
                     - integral[y + bh, x] + integral[y, x])
            mean = total / (bw * bh)
            cx, cy = (x + bw / 2) / w - 0.5, (y + bh / 2) / h - 0.5
            centred = math.exp(-(cx ** 2 + cy ** 2) / (2 * 0.24 ** 2))
            score = mean * (0.4 + 0.6 * centred)
            if score > best:
                best, best_at = score, (x, y)
    best = round(float(best), 4)
    if subject_area is not None and subject_area < SMALL_SUBJECT:
        return None, best
    if best_at is None or best < floor:
        return None, best
    sx, sy = WIDTH / w, HEIGHT / h
    x, y = best_at
    return (x * sx, y * sy, bw * sx, bh * sy), best


# --- drawing -----------------------------------------------------------------------------

def _font(size):
    from pipeline import thumbnail
    return thumbnail._font(size)


def ease_in_out(t):
    return grid.ease(t)


def ease_out_cubic(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def ease_out_back(t, s=1.6):
    t = min(max(t, 0.0), 1.0) - 1
    return t * t * ((s + 1) * t + s) + 1


_DIGITS = {}


def digit_image(n, size=400):
    """A big number on a coloured disc with a white ring: the countdown."""
    key = (n, size)
    if key in _DIGITS:
        return _DIGITS[key]
    colours = {3: (255, 92, 92), 2: (255, 196, 0), 1: (40, 210, 90)}
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ring = max(10, size // 22)
    d.ellipse([0, 0, size - 1, size - 1], fill=(255, 255, 255, 255))
    d.ellipse([ring, ring, size - 1 - ring, size - 1 - ring], fill=colours.get(n, BRAND) + (255,))
    font = _font(int(size * 0.62))
    text = str(n)
    box = d.textbbox((0, 0), text, font=font, stroke_width=14)
    d.text(((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]),
           text, font=font, fill=(255, 255, 255), stroke_width=14, stroke_fill=(22, 28, 70))
    _DIGITS[key] = img
    return img


def question_badge(size=170):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, size - 1, size - 1], fill=(255, 255, 255, 240))
    d.ellipse([10, 10, size - 11, size - 11], fill=(255, 92, 170, 255))
    font = _font(int(size * 0.66))
    box = d.textbbox((0, 0), "?", font=font, stroke_width=8)
    d.text(((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]),
           "?", font=font, fill=(255, 255, 255), stroke_width=8, stroke_fill=(22, 28, 70))
    return img


def _scaled_about_centre(img, scale):
    """`img` scaled about the frame's centre by one affine resample, exact and float."""
    if abs(scale - 1.0) < 1e-6:
        return img
    s = 1.0 / scale
    cx, cy = WIDTH / 2, HEIGHT / 2
    return img.transform((WIDTH, HEIGHT), Image.AFFINE,
                         (s, 0, cx - s * cx, 0, s, cy - s * cy), Image.BICUBIC)


def _paste_centre(frame, overlay, scale, alpha, centre=(WIDTH / 2, HEIGHT / 2)):
    if scale <= 0.01 or alpha <= 0.01:
        return
    w, h = max(1, int(overlay.width * scale)), max(1, int(overlay.height * scale))
    o = overlay.resize((w, h), Image.LANCZOS)
    if alpha < 1:
        a = o.getchannel("A").point(lambda p: int(p * alpha))
        o.putalpha(a)
    frame.alpha_composite(o, (int(centre[0] - w / 2), int(centre[1] - h / 2)))


class Confetti:
    """A burst from the middle of the frame: deterministic, with gravity, gone in a second."""

    def __init__(self, seed, count=140, life=1.0):
        rng = random.Random(seed)
        palette = [(255, 92, 92), (255, 196, 0), (40, 210, 90), (46, 196, 255),
                   (190, 110, 255), (255, 120, 200), (255, 255, 255)]
        self.life = life
        self.bits = []
        for _ in range(count):
            angle = rng.uniform(0, 2 * math.pi)
            speed = rng.uniform(500, 1500)
            self.bits.append({
                "vx": math.cos(angle) * speed, "vy": math.sin(angle) * speed - 500,
                "w": rng.uniform(14, 26), "h": rng.uniform(8, 14),
                "spin": rng.uniform(-9, 9), "turn": rng.uniform(0, math.pi),
                "colour": rng.choice(palette)})

    def draw(self, frame, age):
        if not 0 <= age < self.life:
            return
        layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        fade = 1.0 if age < self.life * 0.6 else max(0.0, (self.life - age) / (self.life * 0.4))
        for b in self.bits:
            x = WIDTH / 2 + b["vx"] * age
            y = HEIGHT / 2 + b["vy"] * age + 0.5 * 1800 * age * age
            a = b["turn"] + b["spin"] * age
            cw, sw = math.cos(a), math.sin(a)
            hw, hh = b["w"] / 2, b["h"] / 2
            pts = [(x + dx * cw - dy * sw, y + dx * sw + dy * cw)
                   for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
            d.polygon(pts, fill=b["colour"] + (int(255 * fade),))
        frame.alpha_composite(layer)


def riddle_and_reveal_frames(still, piece_box, label, t, seed, workers=6):
    """Raw RGB frames for the turn from its start to the moment the clip starts playing.

    `still` is the clip's frame at the reveal, 1920x1080; `piece_box` the detail to cut, or
    None for the blurred riddle; `label` the name as an RGBA image; `t` the timeline.
    """
    full = still.convert("RGB")
    if piece_box:
        x, y, w, h = piece_box
        riddle = full.transform((WIDTH, HEIGHT), Image.EXTENT, (x, y, x + w, y + h),
                                Image.BICUBIC)
    else:
        riddle = full.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    badge = question_badge()
    riddle_rgba = riddle.convert("RGBA")
    riddle_rgba.alpha_composite(badge, (WIDTH - badge.width - 48, 48))
    brand = Image.new("RGBA", (WIDTH, HEIGHT), BRAND + (255,))
    full_rgba = full.convert("RGBA")
    confetti = Confetti(seed)

    end = t["frozen_until"]
    frames = int(round(end * FPS))
    move_frames = max(2, int(round(REVEAL_MOVE * FPS)))
    flight = grid.zoom_geometry(piece_box, move_frames, into=False, spin=0.0) if piece_box else None

    def frame_at(i):
        now = i / FPS
        if now < t["riddle"]:
            e = ease_in_out(now / t["riddle"])
            img = _scaled_about_centre(riddle_rgba, 0.92 + 0.08 * e)
            img = Image.blend(brand, img, e)
        elif now < t["reveal"]:
            img = riddle_rgba.copy()
            if now >= t["countdown"]:
                k = int(now - t["countdown"])
                u = (now - t["countdown"]) - k
                n = COUNT - k
                if n >= 1:
                    scale = 0.35 + 0.65 * ease_out_back(min(u / 0.28, 1.0))
                    alpha = 1.0 if u < 0.8 else max(0.0, (1.0 - u) / 0.2)
                    _paste_centre(img, digit_image(n), scale, alpha)
        else:
            since = now - t["reveal"]
            if piece_box and since < REVEAL_MOVE:
                j = min(int(round(since * FPS)), move_frames - 1)
                img = grid.draw_zoom_frame(full, flight[j]).convert("RGBA")
            elif not piece_box and since < 0.35:
                img = _scaled_about_centre(full_rgba, 1.10 - 0.10 * ease_out_cubic(since / 0.35))
            else:
                img = full_rgba.copy()
            confetti.draw(img, since)
            shown = now - t["answer"]
            if shown >= 0:
                e = ease_out_cubic(shown / 0.3)
                lab = label.copy()
                lab.putalpha(lab.getchannel("A").point(lambda p: int(p * e)))
                y = HEIGHT - label.height - 70 + int(round(40 * (1 - e)))
                img.alpha_composite(lab, ((WIDTH - label.width) // 2, y))
        return img.convert("RGB").tobytes()

    with ThreadPoolExecutor(workers) as pool:
        for start in range(0, frames, workers * 2):
            for data in pool.map(frame_at, range(start, min(frames, start + workers * 2))):
                yield data


def encode(frames, out_path, timeout=1800):
    """Pipe raw frames into the same encoder settings every other piece uses, so the concat
    demuxer can join them without re-encoding."""
    out_path = Path(out_path)
    args = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
            "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "21", "-pix_fmt", "yuv420p", "-loglevel", "error", str(out_path)]
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=errors)
        try:
            for frame in frames:
                proc.stdin.write(frame)
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass
        if proc.wait(timeout=timeout) != 0:
            errors.seek(0)
            raise RuntimeError(f"ffmpeg could not encode {out_path.name}: "
                               f"{errors.read()[-400:].decode('utf-8', 'replace')}")
    return out_path


# --- the "Guess who?" card ---------------------------------------------------------------

def guess_card_frames(seconds, workers=6):
    """The full-screen card between the halves: the board's sky, a sunburst, the words."""
    from pipeline import thumbnail
    base = Image.new("RGB", (WIDTH, HEIGHT))
    d = ImageDraw.Draw(base)
    top, bottom = (46, 196, 255), (120, 92, 255)
    for y in range(HEIGHT):
        k = y / (HEIGHT - 1)
        d.line([(0, y), (WIDTH, y)], fill=tuple(round(a + (b - a) * k) for a, b in zip(top, bottom)))
    rays = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rays)
    for i in range(20):
        a0, a1 = math.radians(i * 18), math.radians(i * 18 + 9)
        far = WIDTH * 1.4
        rd.polygon([(WIDTH / 2, HEIGHT / 2),
                    (WIDTH / 2 + far * math.cos(a0), HEIGHT / 2 + far * math.sin(a0)),
                    (WIDTH / 2 + far * math.cos(a1), HEIGHT / 2 + far * math.sin(a1))],
                   fill=(255, 255, 255, 34))
    base = Image.alpha_composite(base.convert("RGBA"), rays.filter(ImageFilter.GaussianBlur(5)))

    font = _font(250)
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    text = "Guess who?"
    box = probe.textbbox((0, 0), text, font=font, stroke_width=20)
    words = Image.new("RGBA", (box[2] - box[0] + 60, box[3] - box[1] + 60), (0, 0, 0, 0))
    ImageDraw.Draw(words).text((30 - box[0], 30 - box[1]), text, font=font,
                               fill=(255, 222, 0), stroke_width=20, stroke_fill=(22, 28, 70))
    shadow = Image.new("RGBA", words.size, (0, 20, 60, 0))
    shadow.putalpha(words.getchannel("A").point(lambda p: int(p * 0.5)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    brand = Image.new("RGBA", (WIDTH, HEIGHT), BRAND + (255,))
    frames = int(round(seconds * FPS))

    def frame_at(i):
        now = i / FPS
        img = base.copy()
        grow = ease_out_back(min(now / 0.5, 1.0))
        breathe = 1.0 + 0.025 * math.sin(2 * math.pi * max(0.0, now - 0.5) / 1.6)
        scale = (0.3 + 0.7 * grow) * breathe
        _paste_centre(img, shadow, scale, 1.0, (WIDTH / 2, HEIGHT / 2 + 14))
        _paste_centre(img, words, scale, 1.0)
        tail = seconds - now
        if tail < OUT:
            img = Image.blend(brand, img, max(0.0, tail / OUT))
        return img.convert("RGB").tobytes()

    with ThreadPoolExecutor(workers) as pool:
        for start in range(0, frames, workers * 2):
            for data in pool.map(frame_at, range(start, min(frames, start + workers * 2))):
                yield data


# --- sound -------------------------------------------------------------------------------

SFX_DIR = Path(__file__).resolve().parent.parent / "assets" / "sfx"

# How far under the voice each effect sits, in dB of active loudness. "Effects not louder than
# the voice" is the rule; these are all below it, and the tick is meant to be heard rather
# than noticed. The levels are measured on the actual files, then read back off the mix.
UNDER_VOICE = {"tick": 14.0, "whoosh": 6.0, "pop": 6.0, "sting": 5.0}


def sfx(name):
    found = sorted(SFX_DIR.glob(f"{name}.*"))
    if not found:
        raise RuntimeError(f"no {name} sound in {SFX_DIR}; run scripts/find_sfx.py --keep")
    return found[0]


def active_db(path, start=None, length=None, floor=-45.0):
    """The loudness of the part of a file that is not silence, in dBFS RMS.

    Not integrated LUFS: a tick is a twentieth of a second, and loudness integration gates
    anything that short away to nothing. The RMS of the non-silent 10 ms frames compares a
    tick and a sentence on the same terms.
    """
    args = ["ffmpeg", "-v", "error"]
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(path)]
    if length is not None:
        args += ["-t", f"{length:.3f}"]
    raw = subprocess.run(args + ["-ac", "1", "-ar", "22050", "-f", "s16le", "-"],
                         capture_output=True, timeout=120).stdout
    a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if len(a) < 220:
        return -120.0
    frames = a[:len(a) // 220 * 220].reshape(-1, 220)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-7))
    live = rms[db > floor]
    if not len(live):
        return -120.0
    return float(20 * np.log10(np.sqrt((live ** 2).mean())))


_CHANNELS = {}


def _channels(path):
    key = str(path)
    if key not in _CHANNELS:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                              "-show_entries", "stream=channels", "-of", "csv=p=0", key],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        _CHANNELS[key] = int(out or 2)
    return _CHANNELS[key]


def loudest_db(path, window=0.1):
    """The loudest 100 ms of a file, in dBFS RMS. An effect is set by this rather than by its
    average: the sting's opening beeps were 6 dB above its own average, which put the start of
    the "Guess who?" card 1.4 dB over the voice though the average sat 5 dB under it."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "22050",
                          "-f", "s16le", "-"], capture_output=True, timeout=120).stdout
    a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    # Never a window longer than the sound: a 35 ms tick measured over 100 ms is averaged with
    # 65 ms of nothing and comes out 3 dB quieter than it plays.
    n = max(1, min(int(22050 * window), len(a)))
    frames = a[:len(a) // n * n].reshape(-1, n)
    return float(20 * np.log10(max(np.sqrt((frames ** 2).mean(axis=1)).max(), 1e-7)))


def mix(items, total, out_path, timeout=600):
    """[(path, start, gain_db)] laid on a silent track of `total` seconds, nothing normalised.

    amix with normalize=0, so a sound is exactly as loud as it was measured to be: the default
    divides every input by the number of inputs, which is how levels stop being the levels.
    """
    out_path = Path(out_path)
    args = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", f"{total:.3f}", "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100"]
    chains, labels = [], ["[0:a]"]
    for n, (path, start, gain) in enumerate(items, start=1):
        args += ["-i", str(path)]
        ms = int(round(start * 1000))
        # A mono voice put into stereo by aformat lands at -3 dB in each channel, the stereo
        # effects do not, and so every effect came out three dB louder against the voice than
        # it was set to - measured on the first full build. Mono is copied to both channels
        # at full level instead.
        up = ("pan=stereo|c0=c0|c1=c0," if _channels(path) == 1 else "")
        chains.append(f"[{n}:a]aresample=44100,{up}aformat=sample_fmts=fltp:"
                      f"channel_layouts=stereo,volume={gain:.2f}dB,adelay={ms}|{ms}[s{n}]")
        labels.append(f"[s{n}]")
    graph = ";".join(chains + [f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:"
                               f"duration=first,atrim=0:{total:.3f}[a]"])
    args += ["-filter_complex", graph, "-map", "[a]", "-ar", "44100", "-ac", "2",
             "-c:a", "aac", str(out_path)]
    subprocess.run(args, check=True, capture_output=True, timeout=timeout)
    return out_path


_LEVELS = {}


def _level(name, voice_db):
    """How much louder than the voice this effect is as it stands, in dB."""
    if name not in _LEVELS:
        _LEVELS[name] = loudest_db(sfx(name))
    return _LEVELS[name] - voice_db


def effect_gain(name, voice_db):
    """The gain that puts an effect UNDER_VOICE[name] dB below the voice."""
    return -UNDER_VOICE[name] - _level(name, voice_db)


# --- one turn ----------------------------------------------------------------------------

STILL_CHAIN = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
               f"crop={WIDTH}:{HEIGHT},eq=saturation=1.30:contrast=1.10")
START_IN_CLIP = 1.0               # where in the clip the frozen frame is taken
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def still_from(source, at, dst):
    """The frame the riddle is cut from and the reveal opens onto, through exactly the chain
    the playing clip goes through afterwards - so the cut from frozen to moving is invisible."""
    dst = Path(dst)
    if not dst.exists():
        is_image = Path(source).suffix.lower() in IMAGE_SUFFIXES
        args = ["ffmpeg", "-y", "-v", "error"]
        args += (["-i", str(source)] if is_image else ["-ss", f"{at:.3f}", "-i", str(source)])
        subprocess.run(args + ["-vf", STILL_CHAIN, "-frames:v", "1", str(dst)],
                       check=True, capture_output=True, timeout=300)
    return Image.open(dst).convert("RGB")


def answer_segment(source, at, seconds, label_png, dst, timeout=900):
    """The clip playing on from the frozen frame, with the name, then out to the brand colour."""
    dst = Path(dst)
    colour = "0x%02X%02X%02X" % BRAND
    is_image = Path(source).suffix.lower() in IMAGE_SUFFIXES
    head = (["-loop", "1", "-i", str(source)] if is_image else
            ["-stream_loop", "-1", "-ss", f"{at:.3f}", "-i", str(source)])
    args = ["ffmpeg", "-y", "-v", "error", *head, "-loop", "1", "-i", str(label_png),
            "-t", f"{seconds:.4f}", "-filter_complex",
            f"[0:v]{STILL_CHAIN},fps={FPS}[v];[v][1:v]overlay=(W-w)/2:H-h-70,"
            f"fade=t=out:st={max(seconds - OUT, 0):.4f}:d={OUT}:color={colour}[o]",
            "-map", "[o]", "-an", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "21", "-pix_fmt", "yuv420p", str(dst)]
    subprocess.run(args, check=True, capture_output=True, timeout=timeout)
    return dst


def build_turn(turn, card, source, sound, question, answer, label_png, hold, work, voice_db,
               subject_area=None):
    """([videos], audio, report) for one turn of the game, video and audio the same length."""
    from core import tts
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    stem = f"turn_{turn:02d}"
    q_len, a_len = tts.duration(question), tts.duration(answer)
    t = timeline(q_len, a_len, sound is not None, hold)

    still = still_from(source, START_IN_CLIP, work / f"{stem}_still.png")
    box, detail = choose_piece(still, subject_area=subject_area)
    label = Image.open(label_png).convert("RGBA")
    n_head = int(round(t["frozen_until"] * FPS))
    n_total = int(round(t["end"] * FPS))
    # The length is in the name: a rerun with a different hold must not pick up a picture made
    # for another length and pair it with a sound made for this one.
    head = work / f"{stem}_{n_total}_a.mp4"
    if not head.exists():
        encode(riddle_and_reveal_frames(still, box, label, t, seed=turn * 7 + 1), head)
    tail = work / f"{stem}_{n_total}_b.mp4"
    if not tail.exists():
        answer_segment(source, START_IN_CLIP, (n_total - n_head) / FPS, label_png, tail)

    hit = "whoosh" if box else "pop"
    items = [(question, t["question"], 0.0), (answer, t["answer"], 0.0),
             (sfx(hit), t["reveal"], effect_gain(hit, voice_db))]
    items += [(sfx("tick"), t["countdown"] + k, effect_gain("tick", voice_db))
              for k in range(COUNT)]
    if sound is not None:
        items += [(sound, t["sound1"], 0.0), (sound, t["sound2"], 0.0)]
    audio = mix(items, n_total / FPS, work / f"{stem}_{n_total}.m4a")
    report = {"subject": card["subject"], "seconds": round(n_total / FPS, 2),
              "riddle": "piece" if box else "blur", "detail": detail,
              "countdown_at": round(t["countdown"], 2), "reveal_at": round(t["reveal"], 2),
              "timeline": t}
    return [head, tail], audio, report


def build_guess_card(line, work, voice_db):
    """(video, audio, seconds) for the "Guess who?" card: the sting, the line, then out."""
    from core import tts
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    seconds = max(3.0, 0.6 + tts.duration(line) + 0.6)
    seconds = round(seconds * FPS) / FPS
    video = work / f"guess_{int(round(seconds * FPS))}.mp4"
    if not video.exists():
        encode(guess_card_frames(seconds), video)
    # Against this line, not the turns' questions: it is said in a different register and
    # came out quieter, which left the sting 0.7 dB over it when set from a question.
    audio = mix([(sfx("sting"), 0.0, effect_gain("sting", active_db(line))), (line, 0.6, 0.0)],
                seconds, work / f"guess_{int(round(seconds * FPS))}.m4a")
    return video, audio, seconds
