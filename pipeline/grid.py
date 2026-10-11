"""The board the video is played on: every subject visible at once, ticked off one by one.

A child who cannot yet count still understands a board filling up. So the video opens on all
the subjects at once - one bright still from each clip, in its own frame - and then each card
is a move: the cell lights up, grows to fill the screen, becomes the real footage, and comes
back with a green tick on it. Between cards the board is shown again, so the child can see
how many are done and how many are left.

All of it is stills and ffmpeg. The board is a composite image built once per video; the grow
and shrink are zoompan over that image, aimed at one cell; the tick is an overlay on the next
version of the board. Nothing here needs a model and nothing is re-encoded twice.

The cost is measured rather than assumed - see docs/grid-cost.md - because a step that looks
cheap and is not is how yt-factory lost two hours to an xfade chain.
"""
import colorsys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.logger import get_logger

log = get_logger("grid")

WIDTH, HEIGHT = 1920, 1080
MARGIN = 70
GAP = 26
BORDER = 10
RADIUS = 34

# Children's colours, in order, so each cell has its own and the board is not one hue. Taken
# round the colour wheel rather than listed, so any number of cells is covered.
SATURATION, VALUE = 0.92, 1.0
BACKDROP_TOP = (46, 196, 255)
BACKDROP_BOTTOM = (120, 92, 255)

TICK_COLOUR = (40, 220, 90)
TICK_EDGE = (255, 255, 255)
DIM = 0.42               # how far an unvisited cell is held back
FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Fredoka-Bold.ttf"


def layout(count, width=WIDTH, height=HEIGHT):
    """(columns, rows, cell width, cell height, [boxes]) for `count` cells.

    Columns are chosen so the cells come out as close to 16:9 as the frame allows, because
    the cell is a window onto a 16:9 clip and anything else crops the animal.
    """
    best = None
    for cols in range(2, count + 1):
        rows = -(-count // cols)
        cw = (width - 2 * MARGIN - (cols - 1) * GAP) / cols
        ch = (height - 2 * MARGIN - (rows - 1) * GAP) / rows
        if cw <= 0 or ch <= 0:
            continue
        waste = abs((cw / ch) - (16 / 9)) + 0.04 * (cols * rows - count)
        if best is None or waste < best[0]:
            best = (waste, cols, rows, cw, ch)
    _waste, cols, rows, cw, ch = best
    boxes = []
    for i in range(count):
        r, c = divmod(i, cols)
        x = MARGIN + c * (cw + GAP)
        y = MARGIN + r * (ch + GAP)
        boxes.append((round(x), round(y), round(cw), round(ch)))
    return cols, rows, round(cw), round(ch), boxes


def cell_colour(index, count):
    hue = (index / max(count, 1)) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, SATURATION, VALUE)
    return (round(r * 255), round(g * 255), round(b * 255))


def _backdrop(size):
    """A bright vertical wash, so the board is never a grey page."""
    w, h = size
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        draw.line([(0, y), (w, y)],
                  fill=tuple(round(a + (b - a) * t)
                             for a, b in zip(BACKDROP_TOP, BACKDROP_BOTTOM)))
    return img


def _rounded(img, radius):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1],
                                           radius=radius, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def tick_badge(size):
    """A green tick in a white ring, for a cell that is done."""
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    draw.ellipse([0, 0, size - 1, size - 1], fill=TICK_COLOUR, outline=TICK_EDGE,
                 width=max(3, size // 12))
    w = max(4, size // 9)
    draw.line([(size * 0.27, size * 0.52), (size * 0.44, size * 0.70)],
              fill=TICK_EDGE, width=w)
    draw.line([(size * 0.44, size * 0.70), (size * 0.75, size * 0.32)],
              fill=TICK_EDGE, width=w)
    return badge


def board(stills, done, out_path, highlight=None, labels=None):
    """One picture of the whole board.

    `stills` is a still per cell, `done` the indices already ticked, `highlight` the cell
    whose turn it is - drawn full strength and with a white ring, while the rest are held
    back so the eye goes to it without anything moving.
    """
    count = len(stills)
    _cols, _rows, cw, ch, boxes = layout(count)
    img = _backdrop((WIDTH, HEIGHT))
    badge = tick_badge(round(min(cw, ch) * 0.42))

    for i, (still, (x, y, w, h)) in enumerate(zip(stills, boxes)):
        with Image.open(still) as raw:
            tile = raw.convert("RGB")
            scale = max(w / tile.width, h / tile.height)
            tile = tile.resize((max(w, round(tile.width * scale)),
                                max(h, round(tile.height * scale))), Image.LANCZOS)
            left = (tile.width - w) // 2
            top = (tile.height - h) // 2
            tile = tile.crop((left, top, left + w, top + h))
        if highlight is not None and i != highlight and i not in done:
            tile = Image.blend(Image.new("RGB", tile.size, (20, 30, 60)), tile, DIM)
        elif highlight is not None and i != highlight:
            tile = Image.blend(Image.new("RGB", tile.size, (20, 30, 60)), tile, 0.75)

        frame = Image.new("RGB", (w + BORDER * 2, h + BORDER * 2),
                          TICK_EDGE if i == highlight else cell_colour(i, count))
        frame.paste(tile, (BORDER, BORDER))
        img.paste(_rounded(frame, RADIUS), (x - BORDER, y - BORDER),
                  _rounded(frame, RADIUS))

        if i in done:
            img.paste(badge, (x + w - badge.width + BORDER // 2, y - BORDER // 2), badge)

    if labels:
        font = ImageFont.truetype(str(FONT), max(22, round(ch * 0.13)))
        try:
            font.set_variation_by_name("Bold")
        except Exception:                                        # noqa: BLE001
            pass
        draw = ImageDraw.Draw(img)
        for i, (text, (x, y, w, h)) in enumerate(zip(labels, boxes)):
            caption = text.upper()
            box = draw.textbbox((0, 0), caption, font=font, stroke_width=5)
            draw.text((x + (w - (box[2] - box[0])) // 2, y + h - (box[3] - box[1]) - 12),
                      caption, font=font, fill=(255, 255, 255), stroke_width=5,
                      stroke_fill=(0, 0, 0))

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=92)
    return out_path


def zoom_filter(box, seconds, fps=30, into=True):
    """A zoompan that flies between the whole board and one cell.

    zoompan works on a scaled-up copy, so the maths is in fractions of the frame: the target
    zoom is how many times the cell has to grow to fill the screen, and the pan keeps the
    cell's centre in the middle while it does.
    """
    x, y, w, h = box
    target = max(WIDTH / max(w, 1), HEIGHT / max(h, 1))
    frames = max(int(seconds * fps), 2)
    cx = (x + w / 2) / WIDTH
    cy = (y + h / 2) / HEIGHT
    if into:
        z = f"1+({target - 1})*on/{frames}"
    else:
        z = f"{target}-({target - 1})*on/{frames}"
    return (f"zoompan=z='{z}'"
            f":x='(iw-iw/zoom)*{cx:.4f}':y='(ih-ih/zoom)*{cy:.4f}'"
            f":d={frames}:s={WIDTH}x{HEIGHT}:fps={fps}")
