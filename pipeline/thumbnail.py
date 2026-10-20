"""Stage 6: the thumbnail - the video's own board, thinned out and given a title.

The video opens on a board of thirty cells and every card is one of them growing to fill the
screen. The cover is that same board with the number cut down, because thirty cells at the
size a phone shows a thumbnail (210x118) is a colour field, not a picture of anything. Eight to
twelve are kept, large, and the ones kept are chosen rather than the first ones: the
brightest, best-known frames, no two of one colour side by side.

  the background  a saturated drawn wash, one palette per video number so a row of covers on a
                  channel page is not one colour;
  the board       8-12 stills in coloured rounded frames - the same frames the video uses;
  the title       "30 ANIMALS for Kids": number, theme, audience. Thick rounded letters with a
                  dark outline, in the palette's accent so it changes from video to video;
  the labels      the name under each cell, if - and only if - it is readable at 210x118.
                  Measured every time, never assumed: a name has to be about 67 px tall at full
                  size to be 11 px tall in the feed, and that does not fit under a cell of a
                  board that has eight of them. When it does not fit, the labels are left off
                  and the frames stand alone.

Nothing is cut out of footage: a subject lifted from stock video came out as a shark's eye and
half a platform, so the cell - a real frame, framed - is the unit.
"""
import json
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.logger import get_logger
from pipeline import grid

log = get_logger("thumbnail")

WIDTH, HEIGHT = 1280, 720
SMALL = (210, 118)
JPEG_QUALITY = 92
FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Fredoka-Bold.ttf"

# The wash top to bottom, and the accent the title is filled with. Blue and green come round
# most often because they are the colours a toddler's content wears, but no two videos running
# share one.
PALETTES = [
    ("lagoon", (0, 205, 255), (0, 110, 235), (255, 222, 0)),
    ("lime", (170, 255, 60), (0, 190, 130), (255, 70, 150)),
    ("ocean", (60, 235, 220), (20, 100, 220), (255, 240, 60)),
    ("bubblegum", (255, 110, 199), (150, 60, 255), (255, 235, 60)),
    ("sunburst", (255, 196, 0), (255, 90, 20), (0, 215, 255)),
    ("grape", (190, 120, 255), (90, 40, 220), (120, 255, 190)),
    ("tangerine", (255, 160, 40), (255, 60, 90), (60, 240, 255)),
]

MIN_CELLS, MAX_CELLS = 8, 12
MARGIN = 34
GAP = 22
BORDER = 13
RADIUS = 30
STROKE = 13
OUTLINE = (22, 28, 70)

MIN_SMALL_CAP_PX = 11            # a capital at 210x118; below this a word is a smudge
MIN_CONTRAST = 4.5               # WCAG AA, of the letter against the outline right around it
LABEL_SIZES = range(96, 24, -2)

# What the title calls each kind of video. "animals" etc. are the families plan.py builds a
# video from; the single themes are for a video that really is only that.
COVER_WORD = {
    "animals": "ANIMALS", "vehicles": "VEHICLES", "food": "FRUIT & VEG",
    "farm animals": "FARM ANIMALS", "wild animals": "WILD ANIMALS",
    "sea animals": "SEA ANIMALS", "birds": "BIRDS", "insects": "BUGS",
    "transport": "VEHICLES", "fruit and vegetables": "FRUIT & VEG",
    "animals and machines": "FIRST WORDS",
}

# A frame has to be recognised in the half second a thumbnail gets, which is not the same as
# being well filmed: a leopard in dappled shade is a good clip and a poor cover. These are the
# things a two-year-old already knows by sight, and they get a lift in the ranking, not a pass.
FAMILIAR = {
    "cow", "pig", "sheep", "horse", "chicken", "duck", "goat", "rooster", "lion", "elephant",
    "tiger", "giraffe", "zebra", "monkey", "bear", "dolphin", "whale", "penguin", "shark",
    "turtle", "sea turtle", "octopus", "crab", "owl", "eagle", "parrot", "peacock", "swan",
    "flamingo", "butterfly", "bee", "ladybug", "tractor", "fire truck", "train", "airplane",
    "helicopter", "school bus", "police car", "boat", "motorcycle", "excavator", "banana",
    "apple", "carrot", "strawberry", "watermelon",
}

# What the catalogue measured about each clip's frame when the clip was added (see
# core/vision.frame_contents): how much of it the main thing fills, how many people stand
# about in it, and what built things the describer named. Read here; never asked again.
#
# SMALL_SUBJECT is a share of the frame, and it is the line below which a thing is a speck in a
# cell 47 px wide in the feed. Set from the catalogue's own distribution - see docs/cover.md.
SMALL_SUBJECT = 0.02
# Built things matter on an animal - an orca on a show platform, a dolphin behind aquarium
# glass - and not on a vehicle, which belongs on a street or at a station. See built_penalty.
BUILT_IS_FINE = {"transport"}


def frame_facts(subject, clip_id, book=None):
    """The catalogue's measurement for this clip, or None if it was never measured."""
    if book is None:
        try:
            from pipeline import catalogue
            book = catalogue.load()
        except Exception:                                        # noqa: BLE001
            return None
    for clip in (book.get(subject) or {}).get("clips", []):
        if str(clip.get("id")) == str(clip_id) and "subject_area" in clip:
            return clip
    return None


def _theme_of(subject):
    try:
        import json
        groups = json.loads((Path(__file__).resolve().parent.parent / "assets" /
                             "subjects.json").read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return ""
    return next((t for t, items in groups.items() if subject in items), "")


def unfit_for_cover(subject, facts):
    """Why this frame should not be on a cover, or "" if nothing is known against it."""
    if not facts:
        return ""
    if facts.get("people", 0) > 0 and _theme_of(subject) not in BUILT_IS_FINE:
        # On a vehicle a person is the driver, the rider, the man rowing: part of the thing.
        return f"{facts['people']} people in the frame"
    area = facts.get("subject_area")
    if area is not None and area < SMALL_SUBJECT:
        return f"fills {area:.1%} of the frame"
    return ""


def built_penalty(subject, facts):
    """Built things behind an animal lower a frame's chances; they do not rule it out, because
    the describer that reports them also reports a building beside a chicken in an empty
    field."""
    if facts and facts.get("structures") and _theme_of(subject) not in BUILT_IS_FINE:
        return 0.3
    return 0.0


def palette_for(video_id):
    return PALETTES[int(video_id) % len(PALETTES)]


def _font(size):
    face = ImageFont.truetype(str(FONT), size)
    try:
        face.set_variation_by_name("Bold")
    except Exception:                                            # noqa: BLE001
        pass
    return face


# --- which frames -------------------------------------------------------------------------

def _hsv(path):
    with Image.open(path) as raw:
        small = raw.convert("RGB").resize((96, 54), Image.BILINEAR)
    return np.asarray(small.convert("HSV"), dtype=np.float64) / 255.0


def appeal(path):
    """(score, dominant hue) for a frame: how loud it is and what colour it is.

    Saturation and brightness of the middle of the frame, where the animal is, with dark and
    washed-out pixels discounted - a night shot is high-contrast and no use as a cover. The
    hue is the weighted circular mean of what is vivid, so the caller can keep neighbours
    apart.
    """
    hsv = _hsv(path)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    centre = (slice(10, 44), slice(20, 76))
    sat, val = s[centre], v[centre]
    vivid = float(np.mean(np.clip(sat, 0, 1) * np.clip(val * 1.4, 0, 1)))
    washed = float(np.mean(val < 0.22) + np.mean((sat < 0.12) & (val > 0.85)))
    weight = (s * v) ** 2
    angle = 2 * math.pi * h
    hue = (math.atan2((weight * np.sin(angle)).sum(), (weight * np.cos(angle)).sum())
           / (2 * math.pi)) % 1.0
    return 0.6 * max(vivid - 0.6 * washed, 0.0) + stands_out(hsv) - clutter(hsv), hue


def stands_out(hsv):
    """How far the middle of the frame is, in colour, from the frame's own edge.

    A lion on a rock against blue sky is far from its surroundings; a ladybug in a field of
    leaves is not, and at the size of a thumbnail it is a green rectangle with a speck. This is
    the cheapest stand-in for "is the animal the picture" that needs no model - the catalogue's
    own prominence says 1.00 for nearly every frame, because it records that the subject is
    the animal, not how large the animal is.
    """
    rgb = np.asarray(Image.fromarray((hsv * 255).astype(np.uint8), "HSV").convert("RGB"),
                     dtype=np.float64) / 255.0
    ring = np.concatenate([rgb[:5].reshape(-1, 3), rgb[-5:].reshape(-1, 3),
                           rgb[:, :6].reshape(-1, 3), rgb[:, -6:].reshape(-1, 3)])
    edge = np.median(ring, axis=0)
    centre = rgb[12:42, 26:70].reshape(-1, 3)
    distance = np.sqrt(((centre - edge) ** 2).sum(axis=1)) / math.sqrt(3)
    return float(np.mean(np.clip(distance * 2.2, 0, 1)))


def clutter(hsv):
    """A penalty for a dark band along the bottom: silhouettes of visitors at an aquarium
    window, or a letterbox. Either is a thing in the cover that is not the animal."""
    v = hsv[..., 2]
    bottom, rest = float(v[-10:].mean()), float(v[:-10].mean())
    return max(0.0, (rest - bottom) - 0.20) * 3.0


def choose_frames(candidates, count, book=None):
    """The `count` best of [(subject, still_path, clip_id)], as [(subject, path, score)].

    Frames the catalogue measured as unfit - people about, built things behind an animal, a
    subject that fills almost none of the frame - are set aside first, and only come back if
    there would otherwise not be enough to fill the board. Among the rest, greedy: each pick
    takes the best remaining, less a penalty for every frame already picked of nearly the same
    hue. Without that, a catalogue with a lot of green leaves gives a cover of green rectangles.
    """
    if book is None:
        try:
            from pipeline import catalogue
            book = catalogue.load()
        except Exception:                                        # noqa: BLE001
            book = {}
    fit, unfit = [], []
    for subject, path, clip_id in candidates:
        base, hue = appeal(path)
        facts = frame_facts(subject, clip_id, book)
        score = base + (0.12 if subject in FAMILIAR else 0)
        if facts and facts.get("subject_area") is not None:
            # A little for size: the box under-measures, so this is a nudge and not a ranking.
            score += 0.15 * min(facts["subject_area"] / 0.10, 1.0)
        score -= built_penalty(subject, facts)
        why = unfit_for_cover(subject, facts)
        (unfit if why else fit).append([score, hue, subject, path, why])
    if len(fit) < count:
        log.info("only %d frames are fit for a cover; %d unfit ones fill the rest",
                 len(fit), count - len(fit))
        fit += sorted(unfit, key=lambda r: -r[0])[:count - len(fit)]
    chosen = []
    while fit and len(chosen) < count:
        def adjusted(item):
            close = sum(1 for c in chosen
                        if min(abs(item[1] - c[1]), 1 - abs(item[1] - c[1])) < 0.07)
            return item[0] - 0.09 * close
        best = max(fit, key=adjusted)
        fit.remove(best)
        chosen.append(best)
    return [(s, p, sc) for sc, _h, s, p, _w in chosen]


# --- the picture ---------------------------------------------------------------------------

def background(video_id):
    """A saturated wash with a sunburst and confetti. Drawn, deterministic, no model."""
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
    cx, cy = WIDTH * 0.5, HEIGHT * 0.12
    for i in range(18):
        a0, a1 = math.radians(i * 20 + 4), math.radians(i * 20 + 14)
        far = WIDTH * 1.6
        rdraw.polygon([(cx, cy), (cx + far * math.cos(a0), cy + far * math.sin(a0)),
                       (cx + far * math.cos(a1), cy + far * math.sin(a1))],
                      fill=(255, 255, 255, 30))
    out = Image.alpha_composite(base.convert("RGBA"), rays.filter(ImageFilter.GaussianBlur(6)))
    confetti = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(confetti)
    for _ in range(40):
        x, y = rng.randrange(WIDTH), rng.randrange(HEIGHT)
        r = rng.randrange(7, 15)
        colour = rng.choice([spark, (255, 255, 255), top])
        cdraw.ellipse([x - r, y - r, x + r, y + r], fill=colour + (150,))
    return Image.alpha_composite(out, confetti).convert("RGB")


def title_text(video_id, theme, count):
    """('30 ANIMALS', 'for Kids') - the number is how many cards the video really has."""
    word = COVER_WORD.get((theme or "").lower(), (theme or "FIRST WORDS").upper())
    return f"{count} {word}", "for Kids"


def _title_size(big, small_text):
    """The largest size at which '30 ANIMALS for Kids' fits one line, 'for Kids' at 58%."""
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    for size in range(190, 40, -2):
        a = probe.textbbox((0, 0), big, font=_font(size), stroke_width=STROKE)
        b = probe.textbbox((0, 0), small_text, font=_font(round(size * 0.58)),
                           stroke_width=STROKE)
        if (a[2] - a[0]) + 26 + (b[2] - b[0]) <= WIDTH - 2 * MARGIN:
            return size
    return 40


def draw_title(img, video_id, theme, count):
    """Draw the title; returns (fill mask, whole mask, band bottom, size, font) to measure it."""
    big, small_text = title_text(video_id, theme, count)
    size = _title_size(big, small_text)
    f_big, f_small = _font(size), _font(round(size * 0.58))
    accent = palette_for(video_id)[3]
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    a = probe.textbbox((0, 0), big, font=f_big, stroke_width=STROKE)
    b = probe.textbbox((0, 0), small_text, font=f_small, stroke_width=STROKE)
    total = (a[2] - a[0]) + 26 + (b[2] - b[0])
    left = (WIDTH - total) // 2
    top = MARGIN - a[1] + 4
    base = top + a[3]
    x_small = left + (a[2] - a[0]) + 26 - b[0]
    y_small = base - b[3]

    def paint(layer, dy=0, stroke=True):
        d = ImageDraw.Draw(layer)
        kw = dict(stroke_width=STROKE, stroke_fill=255) if stroke else {}
        d.text((left - a[0], top + dy), big, font=f_big, fill=255, **kw)
        d.text((x_small, y_small + dy), small_text, font=f_small, fill=255, **kw)

    shadow, whole, fill = (Image.new("L", img.size, 0) for _ in range(3))
    paint(shadow, dy=9)
    paint(whole)
    paint(fill, stroke=False)
    img.paste(Image.new("RGB", img.size, (0, 20, 60)), (0, 0),
              shadow.filter(ImageFilter.GaussianBlur(5)).point(lambda p: int(p * 0.55)))
    d = ImageDraw.Draw(img)
    d.text((left - a[0], top), big, font=f_big, fill=accent, stroke_width=STROKE,
           stroke_fill=OUTLINE)
    d.text((x_small, y_small), small_text, font=f_small, fill=(255, 255, 255),
           stroke_width=STROKE, stroke_fill=OUTLINE)
    return fill, whole, top + a[3] + STROKE, size, f_big


# --- the board -----------------------------------------------------------------------------

def layout(count_available, top):
    """(cols, rows, [(x, y, w, h)]) for the largest cells that fit under the title.

    Every column/row split of 8 to 12 cells is tried and the one with the biggest cells wins,
    which in practice is eight in two rows: the number of cells is what has to give when the
    size matters.
    """
    best = None
    area_w = WIDTH - 2 * MARGIN
    area_h = HEIGHT - top - MARGIN
    for n in range(MIN_CELLS, min(MAX_CELLS, count_available) + 1):
        for rows in (1, 2, 3):
            if n % rows:
                continue
            cols = n // rows
            w = (area_w - (cols - 1) * GAP) / cols
            h = (area_h - (rows - 1) * GAP) / rows
            if w < 150 or h < 100:
                continue
            if best is None or w * h > best[0]:
                best = (w * h, cols, rows, w, h)
    if best is None:
        raise RuntimeError(f"no board of {MIN_CELLS}-{MAX_CELLS} cells fits")
    _a, cols, rows, w, h = best
    x0 = (WIDTH - (cols * w + (cols - 1) * GAP)) / 2
    boxes = []
    for i in range(cols * rows):
        r, c = divmod(i, cols)
        boxes.append((round(x0 + c * (w + GAP)), round(top + r * (h + GAP)),
                      round(w), round(h)))
    return cols, rows, boxes


def _without_bars(im, floor=14):
    """Crop black letterbox bars: some stock clips are 16:9 inside a taller or wider frame, and
    a bar inside a cell reads as a hole in it."""
    grey = np.asarray(im.convert("L"), dtype=np.float64)
    rows = np.where(grey.mean(axis=1) > floor)[0]
    cols = np.where(grey.mean(axis=0) > floor)[0]
    if len(rows) < im.height * 0.5 or len(cols) < im.width * 0.5:
        return im
    return im.crop((int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1))


def _cover_crop(path, w, h):
    with Image.open(path) as raw:
        im = _without_bars(raw.convert("RGB"))
    scale = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * scale)), max(h, round(im.height * scale))),
                   Image.LANCZOS)
    left, upper = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((left, upper, left + w, upper + h))


def draw_cells(img, chosen, boxes):
    """The frames, each in a coloured rounded frame with a soft shadow."""
    count = len(boxes)
    shadow = Image.new("L", img.size, 0)
    sd = ImageDraw.Draw(shadow)
    for (x, y, w, h) in boxes:
        sd.rounded_rectangle([x - BORDER, y - BORDER + 9, x + w + BORDER, y + h + BORDER + 9],
                             radius=RADIUS, fill=255)
    img.paste(Image.new("RGB", img.size, (0, 20, 60)), (0, 0),
              shadow.filter(ImageFilter.GaussianBlur(9)).point(lambda p: int(p * 0.5)))
    for i, ((_subject, path, _s), (x, y, w, h)) in enumerate(zip(chosen, boxes)):
        frame = Image.new("RGB", (w + 2 * BORDER, h + 2 * BORDER), grid.cell_colour(i, count))
        frame.paste(_cover_crop(path, w, h), (BORDER, BORDER))
        mask = Image.new("L", frame.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, frame.width - 1, frame.height - 1],
                                               radius=RADIUS, fill=255)
        img.paste(frame, (x - BORDER, y - BORDER), mask)


def fit_labels(chosen, boxes):
    """(size, capital height at 210x118) for the largest size at which every name fits.

    All labels share one size - names of different sizes look like a mistake - so the widest
    name sets it; and a name is never taller than a third of its cell, so it does not cover
    the animal it names.
    """
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    for size in LABEL_SIZES:
        font = _font(size)
        fits = True
        for (subject, _p, _s), (_x, _y, w, h) in zip(chosen, boxes):
            box = probe.textbbox((0, 0), subject.upper(), font=font, stroke_width=6)
            if box[2] - box[0] > w - 16 or box[3] - box[1] > h * 0.34:
                fits = False
                break
        if fits:
            cap = font.getbbox("H")
            return size, (cap[3] - cap[1]) * SMALL[1] / HEIGHT
    return None, 0.0


def draw_labels(img, chosen, boxes, size):
    font = _font(size)
    draw = ImageDraw.Draw(img)
    for (subject, _p, _s), (x, y, w, h) in zip(chosen, boxes):
        text = subject.upper()
        box = draw.textbbox((0, 0), text, font=font, stroke_width=6)
        draw.text((x + (w - (box[2] - box[0])) // 2 - box[0],
                   y + h - (box[3] - box[1]) - 12 - box[1]),
                  text, font=font, fill=(255, 255, 255), stroke_width=6, stroke_fill=OUTLINE)


# --- the check ----------------------------------------------------------------------------

def _lum(rgb):
    c = np.asarray(rgb, dtype=np.float64) / 255
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def title_check(img, fill_mask, whole_mask, font_big):
    """What a viewer gets at 210x118: the capital's height, and the letter against its outline.

    Taken from the actual pixels of the shrunken cover, not from the colours chosen: the mean
    of the letter's core, and the mean of the outline ring right around it.
    """
    cap = font_big.getbbox("H")
    cap_px = (cap[3] - cap[1]) * SMALL[1] / HEIGHT
    small = np.asarray(img.resize(SMALL, Image.LANCZOS).convert("RGB"))
    core = np.asarray(fill_mask.filter(ImageFilter.MinFilter(5)).resize(SMALL, Image.LANCZOS)) > 200
    near = np.asarray(fill_mask.filter(ImageFilter.MaxFilter(5)).resize(SMALL, Image.LANCZOS)) > 30
    whole = np.asarray(whole_mask.resize(SMALL, Image.LANCZOS)) > 100
    ring = whole & ~near
    if core.sum() < 20 or ring.sum() < 10:
        return {"cap_px": round(cap_px, 1), "contrast": 0.0, "ok": False}
    a, b = float(np.mean(_lum(small[core]))), float(np.mean(_lum(small[ring])))
    ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
    return {"cap_px": round(cap_px, 1), "contrast": round(ratio, 1),
            "ok": cap_px >= MIN_SMALL_CAP_PX and ratio >= MIN_CONTRAST}


# --- putting it together -------------------------------------------------------------------

def make(candidates, video_id, theme, count, out_dir):
    """Build the cover from [(subject, still_path, clip_id)]; returns a report dict."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    img = background(video_id)
    fill_mask, whole_mask, band_bottom, size, f_big = draw_title(img, video_id, theme, count)
    cols, rows, boxes = layout(len(candidates), band_bottom + 14)
    chosen = choose_frames(candidates, len(boxes))
    draw_cells(img, chosen, boxes)

    label_size, label_cap = fit_labels(chosen, boxes)
    labelled = label_size is not None and label_cap >= MIN_SMALL_CAP_PX
    if labelled:
        draw_labels(img, chosen, boxes, label_size)

    check = title_check(img, fill_mask, whole_mask, f_big)
    path = out_dir / "thumbnail.jpg"
    img.save(path, "JPEG", quality=JPEG_QUALITY)
    small = out_dir / "thumb_small.jpg"
    img.resize(SMALL, Image.LANCZOS).save(small, "JPEG", quality=JPEG_QUALITY)
    return {"path": path, "small": small, "palette": palette_for(video_id)[0],
            "title": " ".join(title_text(video_id, theme, count)), "title_size": size,
            "cells": len(boxes), "grid": f"{cols}x{rows}",
            "subjects": [s for s, _p, _x in chosen], "labels": labelled,
            "label_cap_if_drawn": round(label_cap, 1), "label_size_that_fits": label_size,
            "readability": check}


def _stills(cards, out):
    """[(subject, still, clip_id)] from the stills the render stage already made, else cut."""
    import subprocess
    found = []
    for card in cards:
        still = out / "cards" / f"still_{card['idx']:02d}.jpg"
        if not still.exists():
            clip = out / "clips" / f"{card['idx']:02d}_{card['subject'].replace(' ', '_')}.mp4"
            source = clip if clip.exists() else card.get("image_path")
            if not source:
                continue
            still.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-y", "-ss", "2", "-i", str(source), "-frames:v", "1",
                            "-vf", "scale=640:360,eq=saturation=1.35:contrast=1.08",
                            str(still)], capture_output=True, timeout=300)
        if still.exists():
            found.append((card["subject"], still, card.get("clip_id")))
    return found


def run(video_id, cfg, db, output_dir):
    out = Path(output_dir)
    cards = db.get_cards(video_id)
    if not cards:
        raise RuntimeError("there are no cards to take a thumbnail from")
    candidates = _stills(cards, out)
    if len(candidates) < MIN_CELLS:
        raise RuntimeError(f"only {len(candidates)} pictures to build a cover from, "
                           f"a board needs {MIN_CELLS}")
    video = db.get_video(video_id) or {}
    result = make(candidates, video_id, video.get("theme"), len(cards), out)

    check = result["readability"]
    message = (f"{result['palette']}, {result['grid']} cells, title {result['title_size']}px, "
               f"labels {'on' if result['labels'] else 'off'} (they would be "
               f"{result['label_cap_if_drawn']}px at 210x118, need {MIN_SMALL_CAP_PX}), "
               f"title capital {check['cap_px']}px (need {MIN_SMALL_CAP_PX}), letter against "
               f"outline {check['contrast']}:1 (need {MIN_CONTRAST})")
    if check["ok"]:
        log.info("thumbnail readable: %s", message)
    else:
        log.warning("the cover failed the feed-size check: %s", message)
        db.log_event(video_id, "thumbnail", "warning", message)
    (out / "thumbnail.json").write_text(
        json.dumps({k: str(v) for k, v in result.items()}, indent=2), encoding="utf-8")
    db.update_video(video_id, thumbnail_path=str(result["path"]))
    db.log_event(video_id, "thumbnail", "info", message)
    return True
