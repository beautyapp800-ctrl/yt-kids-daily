"""Stage 6: the thumbnail - 1280x720, bright, and readable at the size a phone shows it.

The opposite of yt-factory's in every way that matters. That channel wanted a dark frame with
one light in it; this one is for a four-year-old scrolling past on a tablet, so: the subject
big and in colour, two or three fat rounded words, a heavy outline, and a band of flat colour
behind the type so nothing shows through it.

Three rules from the brief, all checked here rather than hoped for:

- the words are not the title. The title says "25 Sea Animals for Kids"; the thumbnail says
  "LISTEN!" or "WHO SAYS MOO?" - a different thing, because repeating the title wastes the
  one line a child might read;
- the colour accent changes from video to video, deterministically from the video number, so
  a row of these on a channel page is not one colour;
- it is measured at 210x118: the capital height of the smaller line and the contrast of each
  line against what is actually behind it there. If a layout fails, a smaller word count or a
  bigger size is tried, and the stage says so loudly rather than shipping it quietly.
"""
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from core.logger import get_logger

log = get_logger("thumbnail")

WIDTH, HEIGHT = 1280, 720
SMALL = (210, 118)
JPEG_QUALITY = 92
FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Fredoka-Bold.ttf"

# Bright, saturated, and distinct from each other at thumbnail size. The second colour of each
# pair is the band behind the type; the first is the word on it.
# Bright, saturated bands, distinct from each other at thumbnail size. The ink is NOT fixed:
# white on a sunshine-yellow band measured 2.2:1, well under the 4.5 the check wants, so the
# word is set in whichever of white or near-black actually reads on that band - which is what
# a sign-writer would have done without being asked.
BANDS = [
    ("sunshine", (255, 170, 0)),
    ("berry", (214, 51, 132)),
    ("leaf", (34, 160, 72)),
    ("sky", (0, 132, 209)),
    ("grape", (123, 63, 190)),
    ("tangerine", (240, 90, 34)),
    ("teal", (0, 150, 150)),
]
INKS = [(255, 255, 255), (26, 20, 10)]


def _relative_luminance(rgb):
    c = [v / 255 for v in rgb]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ink_for(band):
    """Whichever of white or near-black reads better on this band."""
    best, best_ratio = INKS[0], 0.0
    for ink in INKS:
        a, b = _relative_luminance(ink), _relative_luminance(band)
        ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
        if ratio > best_ratio:
            best, best_ratio = ink, ratio
    return best


ACCENTS = [(name, ink_for(band), band) for name, band in BANDS]

SATURATION = 1.35
BRIGHTNESS = 1.08
STROKE = 8
MARGIN = 44
# The band may not eat the picture. The brief asks for the subject big and close, and the
# first build put a 190px two-line block behind a full-width band that covered 55% of the
# frame - the whale was behind it. Two or three fat words across the bottom third is the
# shape; anything more and the thumbnail is a poster with a photograph behind it.
MAX_BLOCK_FRACTION = 0.30
MIN_SMALL_CAP_PX = 11            # a capital of the SMALLER line, at 210x118
MIN_CONTRAST = 4.5               # WCAG AA for large text


def accent_for(video_id):
    return ACCENTS[int(video_id) % len(ACCENTS)]


def words_for(cards, video_id):
    """Candidate line-sets for the tile, shortest first, never the title.

    One line before two: the block may only take a third of the frame, and inside that a
    single line can be set half again as large as two - which is the difference between
    passing the feed-size check and failing it by half a pixel. A question beats a label,
    because a child who is asked something looks for the answer, and the answer is the video.
    """
    shapes = [
        [["WHAT'S", "THIS?"]],
        [["WHO", "SAYS", "THAT?"]],
        [["LISTEN!"]],
        [["GUESS", "THE", "SOUND!"]],
        [["CAN", "YOU", "SAY", "IT?"]],
    ]
    chosen = shapes[int(video_id) % len(shapes)]
    words = chosen[0]
    options = [[words]]                                  # one line
    if len(words) > 1:                                   # then split in two
        cut = max(1, len(words) // 2)
        options.append([words[:cut], words[cut:]])
    return options


def background(path, accent):
    """The card's picture, pushed bright and saturated - this is children's television."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = img.size
        side = min(w, round(h * WIDTH / HEIGHT))
        box = ((w - side) // 2, 0, (w - side) // 2 + side, min(h, round(side * HEIGHT / WIDTH)))
        img = img.crop(box).resize((WIDTH, HEIGHT), Image.LANCZOS)
    img = ImageEnhance.Color(img).enhance(SATURATION)
    return ImageEnhance.Brightness(img).enhance(BRIGHTNESS)


def _font(size):
    face = ImageFont.truetype(str(FONT), size)
    try:
        face.set_variation_by_name("Bold")
    except Exception:                                            # noqa: BLE001
        pass
    return face


def layouts(lines):
    """Candidate sizes, largest first, that fit the frame with a margin."""
    out = []
    for size in range(140, 60, -4):
        face = _font(size)
        widths = [face.getbbox(" ".join(l), stroke_width=STROKE)[2] for l in lines]
        if max(widths) > WIDTH - MARGIN * 2:
            continue
        heights = [face.getbbox(" ".join(l), stroke_width=STROKE)[3] for l in lines]
        block = sum(heights) + 14 * (len(lines) - 1)
        if block > HEIGHT * MAX_BLOCK_FRACTION:
            continue
        out.append({"size": size, "height": block, "width": max(widths)})
    return out


def draw(img, lines, layout, accent):
    """The words on a flat band, bottom-aligned.

    Returns (masks, backdrop). The backdrop is the image with the band on it but WITHOUT the
    words: measuring the contrast of white text against a picture that already has the white
    text in it gives 1.0:1 every time, which is what the first version did and why every
    thumbnail "failed" its own check.
    """
    _name, ink, band = accent
    face = _font(layout["size"])
    draw_on = ImageDraw.Draw(img, "RGBA")
    top = HEIGHT - MARGIN - layout["height"]
    # A band, not a scrim: a four-year-old reads a word on a flat colour, and a gradient over
    # a bright photograph leaves parts of the word sitting on a leaf.
    draw_on.rectangle([0, top - 18, WIDTH, HEIGHT - MARGIN + 18], fill=(*band, 238))
    backdrop = img.copy()
    masks, y = [], top
    for line in lines:
        text = " ".join(line)
        box = face.getbbox(text, stroke_width=STROKE)
        x = (WIDTH - (box[2] - box[0])) // 2 - box[0]
        draw_on.text((x, y - box[1]), text, font=face, fill=ink,
                     stroke_width=STROKE, stroke_fill=(0, 0, 0, 200))
        mask = Image.new("L", (WIDTH, HEIGHT), 0)
        ImageDraw.Draw(mask).text((x, y - box[1]), text, font=face, fill=255,
                                  stroke_width=STROKE, stroke_fill=255)
        masks.append(mask)
        y += (box[3] - box[1]) + 14
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


def readability(backdrop, masks, layout, accent):
    """What survives at 210x118."""
    scale = SMALL[1] / HEIGHT
    cap = _font(layout["size"]).getbbox("H")
    cap_px = (cap[3] - cap[1]) * scale
    small = np.asarray(backdrop.convert("L").resize(SMALL, Image.LANCZOS))
    ratios = [contrast(accent[1], small, np.asarray(m.resize(SMALL, Image.LANCZOS)))
              for m in masks]
    return {"cap_px": round(cap_px, 1), "contrast": round(min(ratios), 1),
            "ok": cap_px >= MIN_SMALL_CAP_PX and min(ratios) >= MIN_CONTRAST}


def make(source, options, out_dir, video_id):
    """Build thumbnail.jpg and thumb_small.jpg from the first line-set that reads."""
    out_dir = Path(out_dir)
    accent = accent_for(video_id)
    best, lines = None, options[0]
    for candidate in options:
        for layout in layouts(candidate):
            img = background(source, accent)
            masks, backdrop = draw(img, candidate, layout, accent)
            check = readability(backdrop, masks, layout, accent)
            if check["ok"]:
                best, lines = (img, layout, check), candidate
                break
            if best is None:
                best, lines = (img, layout, check), candidate
        if best and best[2]["ok"]:
            break
    if best is None:
        raise RuntimeError(f"no layout fits any of {options!r}")
    img, layout, check = best

    path = out_dir / "thumbnail.jpg"
    img.save(path, "JPEG", quality=JPEG_QUALITY)
    small = out_dir / "thumb_small.jpg"
    img.resize(SMALL, Image.LANCZOS).save(small, "JPEG", quality=JPEG_QUALITY)
    return {"path": path, "small": small, "accent": accent[0], "lines": lines,
            "font_size": layout["size"], "readability": check, "source": str(source)}


def run(video_id, cfg, db, output_dir):
    out = Path(output_dir)
    cards = db.get_cards(video_id)
    if not cards:
        raise RuntimeError("there are no cards to take a thumbnail from")
    options = words_for(cards, video_id)

    # The picture is the first card's, because that is what the viewer sees first anyway.
    first = cards[0]
    source = first["image_path"]
    if not source:
        clip = out / "clips" / f"00_{first['subject'].replace(' ', '_')}.mp4"
        frame = out / "thumb_source.jpg"
        import subprocess
        subprocess.run(["ffmpeg", "-y", "-ss", "2", "-i", str(clip), "-frames:v", "1",
                        str(frame)], capture_output=True, timeout=300)
        source = frame
    result = make(source, options, out, video_id)

    title = (db.get_video(video_id) or {}).get("seo_title") or ""
    said = " ".join(w for line in result["lines"] for w in line).lower()
    if title and said in title.lower():
        log.warning("the thumbnail repeats the title, which wastes it: %r", said)

    check = result["readability"]
    message = (f"{result['accent']}, {result['font_size']}px, at 210x118 a capital is "
               f"{check['cap_px']}px (need {MIN_SMALL_CAP_PX}) and contrast is "
               f"{check['contrast']}:1 (need {MIN_CONTRAST})")
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
