"""Stage 6: the thumbnail - drawn, not clipped out of the video.

A frame from the video with a word on it is a screenshot, and in a feed of competitors who
draw theirs it looks like nothing happened. So this one is built:

  the background   drawn here, in code - an acid gradient with a sunburst and confetti. Drawn
                   rather than generated, so it costs no model call and comes out the same
                   every time;
  the subject      cut out of its own footage with rembg, which runs locally. Every candidate
                   is actually cut out and the largest clean one wins, because the catalogue's
                   prominence score ties at 1.00 for half the cards and says nothing about
                   whether an animal will lift off its background;
  the words        two or three, heavy rounded capitals on a dark plate. They are a hook, not
                   the topic: the title says "25 Sea Animals", the tile asks "CAN YOU GUESS?";
  the check        at 210x118, the size a phone shows it - capital height and the contrast of
                   the words against what is really behind them.

What the cut-out can and cannot do, measured on this video's own clips: from the shark clip
the model lifted the animal's EYE, 113x99 of a 1280x720 frame; from the whale clip, the tail
together with part of a handlers' platform; from the penguins, the penguins. The floors below
catch the first kind. They cannot catch the second, which is why the biggest clean cut-out
wins rather than the first, and why a tile that cannot find one falls back to a framed
photograph instead of shipping a bad lift.
"""
import json
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.logger import get_logger

log = get_logger("thumbnail")

WIDTH, HEIGHT = 1280, 720
SMALL = (210, 118)
JPEG_QUALITY = 92
FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Fredoka-Bold.ttf"

# Near-acid palettes: the wash from top to bottom, and the spark colour for the confetti.
# Chosen by video number so a row of these on a channel page is not one colour.
PALETTES = [
    ("lagoon", (0, 224, 255), (0, 120, 255), (255, 214, 0)),
    ("bubblegum", (255, 110, 199), (150, 60, 255), (255, 230, 60)),
    ("lime", (170, 255, 60), (0, 190, 130), (255, 90, 160)),
    ("sunburst", (255, 196, 0), (255, 90, 20), (0, 200, 255)),
    ("grape", (190, 120, 255), (90, 40, 220), (120, 255, 200)),
    ("tangerine", (255, 160, 40), (255, 60, 90), (60, 240, 255)),
    ("ocean", (60, 240, 220), (20, 100, 220), (255, 240, 80)),
]

STROKE = 12
MARGIN = 40
MAX_BLOCK_FRACTION = 0.30
MIN_SMALL_CAP_PX = 11
MIN_CONTRAST = 4.5

CUTOUT_MODEL = "u2net"          # the small u2netp lifted scenery; this one is 176 MB
# Lifting a subject out of real stock footage does not work well enough to ship. Measured on
# this video's own clips: u2netp gave a smear; u2net gave the shark's EYE (113x99 of a
# 1280x720 frame), the whale's tail with part of a handlers' platform, and penguins that were
# semi-transparent where their bellies are white. Hardening the alpha punched holes straight
# through the birds instead. The fallback - the frame in a thick white rounded card on the
# drawn background - is a designed tile every time, so it is the default until the subject can
# be DRAWN clean on a plain background, which is what the picture generator already does and
# what this will use as soon as there are Neurons to do it with.
USE_CUTOUT = False
MAX_CUTOUT_FILL = 0.62          # above this the "cut-out" is just the whole picture
MIN_CUTOUT_HEIGHT = 0.30        # of the source frame; below this it is a detail

HOOKS = [
    [["CAN YOU"], ["GUESS?"]],
    [["WHAT'S"], ["THIS?"]],
    [["LISTEN!"]],
    [["WHO SAYS"], ["THAT?"]],
    [["GUESS THE"], ["SOUND!"]],
]

_SESSION = None


def palette_for(video_id):
    return PALETTES[int(video_id) % len(PALETTES)]


def hook_for(video_id):
    """Line-sets for the words, one line first because it can be set larger."""
    chosen = HOOKS[int(video_id) % len(HOOKS)]
    flat = [w for line in chosen for w in line]
    options = [[flat]] if len(flat) <= 2 else []
    options.append(chosen)
    return options


def _font(size):
    face = ImageFont.truetype(str(FONT), size)
    try:
        face.set_variation_by_name("Bold")
    except Exception:                                            # noqa: BLE001
        pass
    return face


# --- the picture ---------------------------------------------------------------------------

def background(video_id):
    """An acid wash with a sunburst and confetti. Drawn, deterministic, no model."""
    _name, top, bottom, spark = palette_for(video_id)
    rng = random.Random(int(video_id) * 7919)
    base = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(base)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        draw.line([(0, y), (WIDTH, y)],
                  fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))

    rays = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    rdraw = ImageDraw.Draw(rays)
    cx, cy = WIDTH * 0.26, HEIGHT * 0.18
    for i in range(16):
        a0 = math.radians(i * 22.5 + 6)
        a1 = math.radians(i * 22.5 + 17)
        far = WIDTH * 1.6
        rdraw.polygon([(cx, cy),
                       (cx + far * math.cos(a0), cy + far * math.sin(a0)),
                       (cx + far * math.cos(a1), cy + far * math.sin(a1))],
                      fill=(255, 255, 255, 34))
    out = Image.alpha_composite(base.convert("RGBA"),
                                rays.filter(ImageFilter.GaussianBlur(7)))

    confetti = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(confetti)
    for _ in range(46):
        x, y = rng.randrange(WIDTH), rng.randrange(HEIGHT)
        r = rng.randrange(7, 22)
        colour = spark if rng.random() < 0.6 else (255, 255, 255)
        cdraw.ellipse([x, y, x + r, y + r], fill=(*colour, rng.randrange(70, 150)))
    return Image.alpha_composite(out, confetti).convert("RGB")


def _session():
    global _SESSION
    if _SESSION is None:
        from rembg import new_session
        _SESSION = new_session(CUTOUT_MODEL)
    return _SESSION


def cut_out(source, max_height, report=None):
    """The subject lifted off its background, as RGBA, or None if it will not come away."""
    try:
        from rembg import remove
    except ImportError:
        log.warning("rembg is not installed; nothing can be cut out")
        return None
    try:
        with Image.open(source) as raw:
            frame = raw.convert("RGB")
            frame_height = frame.height
            cut = remove(frame, session=_session())
    except Exception as e:                                       # noqa: BLE001
        log.warning("could not cut out of %s: %s", Path(source).name, str(e)[:110])
        return None

    cut = cut.convert("RGBA")
    box = cut.getbbox()
    if not box:
        return None
    cut = cut.crop(box)
    if cut.width < 60 or cut.height < 60:
        return None

    filled = float((np.asarray(cut.split()[3], dtype=np.float64) / 255).mean())
    share = cut.height / max(frame_height, 1)
    if report is not None:
        report.update({"fill": round(filled, 2), "height_share": round(share, 2)})
    if filled > MAX_CUTOUT_FILL or share < MIN_CUTOUT_HEIGHT:
        return None

    scale = max_height / cut.height
    return cut.resize((max(1, round(cut.width * scale)), round(max_height)), Image.LANCZOS)


def with_outline(cut, width=14, colour=(255, 255, 255)):
    """A thick white keyline and a soft shadow, so the cut-out does not float."""
    pad = width * 2 + 18
    size = (cut.width + pad * 2, cut.height + pad * 2)
    grown = cut.split()[3].filter(ImageFilter.MaxFilter(size=max(3, width | 1)))

    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", cut.size, (0, 0, 0, 150)), (pad + 8, pad + 14), grown)
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))

    ring = Image.new("RGBA", size, (0, 0, 0, 0))
    ring.paste(Image.new("RGBA", cut.size, (*colour, 255)), (pad, pad), grown)

    out = Image.alpha_composite(shadow, ring)
    out.paste(cut, (pad, pad), cut)
    return out


def framed_photo(source, height=None):
    """The frame in a thick white rounded card: what the tile uses when nothing cuts out.
    Still a designed tile rather than a screenshot with a word on it."""
    height = height or round(HEIGHT * 0.54)
    with Image.open(source) as raw:
        photo = raw.convert("RGB")
    scale = height / photo.height
    photo = photo.resize((max(1, round(photo.width * scale)), height), Image.LANCZOS)
    width = min(photo.width, round(WIDTH * 0.76))
    left = (photo.width - width) // 2
    photo = photo.crop((left, 0, left + width, height))

    pad = 16
    card = Image.new("RGBA", (width + pad * 2, height + pad * 2), (255, 255, 255, 255))
    card.paste(photo, (pad, pad))
    mask = Image.new("L", card.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card.size[0] - 1, card.size[1] - 1],
                                           radius=40, fill=255)
    out = Image.new("RGBA", card.size, (0, 0, 0, 0))
    out.paste(card, (0, 0), mask)
    return out


# --- which subject -------------------------------------------------------------------------

def ranked(cards):
    """Cards in the order worth trying, best-framed first, by the catalogue's measurement."""
    try:
        from pipeline import catalogue
        book = catalogue.load()
    except Exception:                                            # noqa: BLE001
        return list(cards)

    def score(card):
        for clip in (book.get(card["subject"]) or {}).get("clips", []):
            if str(clip.get("id")) == str(card.get("clip_id")):
                return float(clip.get("prominence") or 0)
        return 0.0

    return sorted(cards, key=lambda c: -score(c))


def pick_subject(cards, out, cut_height, tries=4):
    """(frame, cut-out or None): every candidate is cut out and the biggest clean one wins."""
    import subprocess
    best, first_frame = None, None
    for card in ranked(cards)[:tries]:
        clip = out / "clips" / f"{card['idx']:02d}_{card['subject'].replace(' ', '_')}.mp4"
        source = clip if clip.exists() else card.get("image_path")
        if not source:
            continue
        frame = out / f"thumb_try_{card['idx']:02d}.jpg"
        if not frame.exists():
            subprocess.run(["ffmpeg", "-y", "-ss", "2", "-i", str(source), "-frames:v", "1",
                            "-vf", "scale=1280:-1", str(frame)],
                           capture_output=True, timeout=300)
        if not frame.exists():
            continue
        first_frame = first_frame or frame
        report = {}
        cut = cut_out(frame, cut_height, report)
        log.info("  %s: %s", card["subject"], report or "nothing came away")
        if cut is None:
            continue
        if best is None or report.get("height_share", 0) > best[0]:
            best = (report.get("height_share", 0), frame, cut, card["subject"])

    if best:
        log.info("thumbnail subject: %s, the largest clean cut-out (%.0f%% of its frame)",
                 best[3], best[0] * 100)
        return best[1], best[2]
    log.warning("nothing cut out cleanly; the tile uses a framed photograph")
    return first_frame, None


# --- the words -----------------------------------------------------------------------------

def layouts(lines):
    out = []
    for size in range(150, 60, -4):
        face = _font(size)
        widths = [face.getbbox(" ".join(l), stroke_width=STROKE)[2] for l in lines]
        if max(widths) > WIDTH - MARGIN * 2:
            continue
        heights = [face.getbbox(" ".join(l), stroke_width=STROKE)[3] for l in lines]
        block = sum(heights) + 12 * (len(lines) - 1)
        if block > HEIGHT * MAX_BLOCK_FRACTION:
            continue
        out.append({"size": size, "height": block, "width": max(widths)})
    return out


def draw_words(img, lines, layout):
    """Words on a dark plate across the bottom. Returns (masks, backdrop-without-words).

    A plate, because the background is deliberately acid and white letters on orange measured
    3.1:1 against the 4.5 the check wants. The plate makes the contrast a fact rather than a
    hope about which colour the picture happens to be.
    """
    face = _font(layout["size"])
    top = HEIGHT - MARGIN - layout["height"]
    plate = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle(
        [MARGIN // 2, top - 26, WIDTH - MARGIN // 2, HEIGHT - MARGIN + 22],
        radius=36, fill=(24, 18, 46, 232))
    img.paste(plate, (0, 0), plate)
    backdrop = img.copy()

    masks, y = [], top
    drawer = ImageDraw.Draw(img)
    for line in lines:
        text = " ".join(line)
        box = face.getbbox(text, stroke_width=STROKE)
        x = (WIDTH - (box[2] - box[0])) // 2 - box[0]
        drawer.text((x, y - box[1]), text, font=face, fill=(255, 255, 255),
                    stroke_width=STROKE, stroke_fill=(20, 16, 40))
        mask = Image.new("L", (WIDTH, HEIGHT), 0)
        ImageDraw.Draw(mask).text((x, y - box[1]), text, font=face, fill=255,
                                  stroke_width=STROKE, stroke_fill=255)
        masks.append(mask)
        y += (box[3] - box[1]) + 12
    return masks, backdrop


def _luminance(grey):
    c = np.asarray(grey, dtype=np.float64) / 255
    return np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def contrast(colour, backdrop_small, mask_small):
    where = mask_small > 40
    if not where.any():
        return 0.0
    behind = float(np.percentile(_luminance(backdrop_small[where]), 90))
    grey = 0.2126 * colour[0] + 0.7152 * colour[1] + 0.0722 * colour[2]
    text = float(_luminance(np.array([grey]))[0])
    return (max(text, behind) + 0.05) / (min(text, behind) + 0.05)


def readability(backdrop, masks, layout):
    scale = SMALL[1] / HEIGHT
    cap = _font(layout["size"]).getbbox("H")
    cap_px = (cap[3] - cap[1]) * scale
    small = np.asarray(backdrop.convert("L").resize(SMALL, Image.LANCZOS))
    ratios = [contrast((255, 255, 255), small, np.asarray(m.resize(SMALL, Image.LANCZOS)))
              for m in masks]
    return {"cap_px": round(cap_px, 1), "contrast": round(min(ratios), 1),
            "ok": cap_px >= MIN_SMALL_CAP_PX and min(ratios) >= MIN_CONTRAST}


# --- putting it together ---------------------------------------------------------------------

def make(frame, options, out_dir, video_id, cut=None):
    out_dir = Path(out_dir)
    best, chosen = None, options[0]
    for candidate in options:
        for layout in layouts(candidate):
            img = background(video_id)
            if cut is not None:
                art = with_outline(cut)
                img.paste(art, ((WIDTH - art.width) // 2, round(HEIGHT * 0.04)), art)
            elif frame and Path(frame).exists():
                art = framed_photo(frame)
                img.paste(art, ((WIDTH - art.width) // 2, round(HEIGHT * 0.06)), art)
            masks, backdrop = draw_words(img, candidate, layout)
            check = readability(backdrop, masks, layout)
            if check["ok"]:
                best, chosen = (img, layout, check), candidate
                break
            if best is None:
                best, chosen = (img, layout, check), candidate
        if best and best[2]["ok"]:
            break
    if best is None:
        raise RuntimeError(f"no layout fits any of {options!r}")
    img, layout, check = best

    path = out_dir / "thumbnail.jpg"
    img.save(path, "JPEG", quality=JPEG_QUALITY)
    small = out_dir / "thumb_small.jpg"
    img.resize(SMALL, Image.LANCZOS).save(small, "JPEG", quality=JPEG_QUALITY)
    return {"path": path, "small": small, "palette": palette_for(video_id)[0],
            "lines": chosen, "font_size": layout["size"], "readability": check,
            "cut_out": cut is not None}


def _first_frame(cards, out):
    """A full-size frame from the best-framed card, for the framed-photo tile."""
    import subprocess
    for card in ranked(cards)[:3]:
        clip = out / "clips" / f"{card['idx']:02d}_{card['subject'].replace(' ', '_')}.mp4"
        source = clip if clip.exists() else card.get("image_path")
        if not source:
            continue
        frame = out / f"thumb_try_{card['idx']:02d}.jpg"
        if not frame.exists():
            subprocess.run(["ffmpeg", "-y", "-ss", "2", "-i", str(source), "-frames:v", "1",
                            "-vf", "scale=1280:-1", str(frame)], capture_output=True,
                           timeout=300)
        if frame.exists():
            return frame
    return None


def run(video_id, cfg, db, output_dir):
    out = Path(output_dir)
    cards = db.get_cards(video_id)
    if not cards:
        raise RuntimeError("there are no cards to take a thumbnail from")

    frame, cut = (pick_subject(cards, out, round(HEIGHT * 0.68)) if USE_CUTOUT
                  else (_first_frame(cards, out), None))
    result = make(frame, hook_for(video_id), out, video_id, cut=cut)

    title = (db.get_video(video_id) or {}).get("seo_title") or ""
    said = " ".join(w for line in result["lines"] for w in line).lower()
    if title and said in title.lower():
        log.warning("the thumbnail repeats the title, which wastes it: %r", said)

    check = result["readability"]
    message = (f"{result['palette']}, {result['font_size']}px, "
               f"{'subject cut out' if result['cut_out'] else 'framed photograph'}, "
               f"at 210x118 a capital is {check['cap_px']}px (need {MIN_SMALL_CAP_PX}) "
               f"and contrast is {check['contrast']}:1 (need {MIN_CONTRAST})")
    if check["ok"]:
        log.info("thumbnail readable: %s", message)
    else:
        log.warning("no layout passed the feed-size check, keeping the largest: %s", message)
        db.log_event(video_id, "thumbnail", "warning", message)

    (out / "thumbnail.json").write_text(
        json.dumps({k: str(v) for k, v in result.items()}, indent=2), encoding="utf-8")
    db.update_video(video_id, thumbnail_path=str(result["path"]))
    db.log_event(video_id, "thumbnail", "info", message)
    return True
