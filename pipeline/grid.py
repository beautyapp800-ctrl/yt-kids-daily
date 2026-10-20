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
import math
import os
from concurrent.futures import ThreadPoolExecutor
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
    """The old zoompan flight. Kept only so tests/test_zoom.py can measure it against the
    one that replaced it; nothing in the pipeline calls it.

    A zoompan that flies between the whole board and one cell.

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


# --- the flight between the board and a cell ----------------------------------------------

# zoompan was measured and replaced; see docs/zoom.md. The short of it: it holds the window's
# position in whole pixels, so a flight that should sit still while it grows slides sideways
# by up to 3.5 px from one frame to the next and drifts 8 px overall. Here the window is
# floating point from end to end and the frame is produced by one affine resample, so the
# scale is exact and nothing is ever rounded into place.

SPIN_DEGREES = 3.5       # how far the card tilts mid-flight, and square again on landing


def ease(t):
    """Cubic ease-in-out: away slowly, quickest in the middle, settling at the end.

    A flight at a constant rate reads as mechanical - the thing arrives at full speed and
    stops dead. Children's channels all ease, and this is the cheapest easing that looks
    deliberate rather than springy.
    """
    t = min(max(t, 0.0), 1.0)
    return 4 * t ** 3 if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def _tilt_that_fits(cx, cy, window, wanted, width, height):
    """As much of `wanted` as can be had without the window sampling off the board.

    A tilted rectangle reaches further than a square one, and the cells in the corners have
    nothing to spare: at 18 cells the top-left cell wanted 2.7 degrees and that put its corner
    58 px outside the board, which is a black wedge across the corner of the screen. The tilt
    is therefore as much as fits and no more. It is a smooth function of the same progress
    everything else here follows, so capping it bends the motion rather than breaking it, and
    the cells that lose the most are the corner ones, which have the least room by definition.
    """
    half_w, half_h = window / 2, window * height / width / 2
    room_x = min(cx, width - cx)
    room_y = min(cy, height - cy)
    low, high = 0.0, abs(wanted)
    for _ in range(24):
        mid = (low + high) / 2
        cos, sin = math.cos(math.radians(mid)), math.sin(math.radians(mid))
        fits = (half_w * cos + half_h * sin <= room_x
                and half_w * sin + half_h * cos <= room_y)
        low, high = (mid, high) if fits else (low, mid)
    return math.copysign(low * 0.92, wanted)


def zoom_geometry(box, frames, into=True, spin=SPIN_DEGREES, width=WIDTH, height=HEIGHT):
    """[(centre x, centre y, window width, tilt)] - where to look, frame by frame.

    The window's width is geometric, because the eye reads zoom as a ratio: growing seven
    times over by equal steps of width crawls at the start and lunges at the end.

    The centre is then derived from the width rather than interpolated alongside it. Moving
    both independently looks wrong in a way that is easy to miss in the arithmetic and plain
    on screen: shrinking the window about the board's centre magnifies the distance to an
    off-centre cell faster than the centre can travel, so the cell first slides AWAY from the
    middle and then swings back. Measured on cell 7 it went 107 px the wrong way before
    turning round. So the cell's distance from the middle of the screen is what is
    interpolated - straight down to nothing - and the centre is whatever puts it there.
    """
    x, y, w, h = box
    # The cell seen full screen: widened or heightened to 16:9, because a cell is only nearly
    # 16:9 and the card that follows is exactly it.
    end_width = max(w, h * width / height)
    cx1, cy1 = x + w / 2, y + h / 2
    out = []
    for i in range(frames):
        t = i / (frames - 1) if frames > 1 else 1.0
        progress = ease(t if into else 1 - t)
        window = width * (end_width / width) ** progress
        # The cell sits (cx1 - width/2) from the middle when the whole board is in view, and
        # nothing at all from it on landing. Everything between is that distance, shrinking.
        cx = cx1 - window * (cx1 - width / 2) * (1 - progress) / width
        cy = cy1 - window * (cy1 - height / 2) * (1 - progress) / width
        # A window cannot show what is not on the board. For a cell in a corner the path
        # above asks to look up to 43 px past the edge halfway through, so there the window
        # slides along the edge instead - which is what panning across a picture does when
        # you reach the side of it. Both sides of the max are smooth, so this bends the
        # path; it cannot step it.
        cx = min(max(cx, window / 2), width - window / 2)
        cy = min(max(cy, window * height / width / 2),
                 height - window * height / width / 2)
        # Zero at both ends, so the joins either side of the flight are seamless: the board
        # does not jump as it starts and the card does not land crooked.
        # Late rather than halfway: the tilt needs room around the window, and halfway
        # through the flight the window is still most of the board, so a corner cell could
        # not have any. Peaking at about three quarters it gets its tilt where there is
        # space for it, and still comes back to square on landing.
        wanted = spin * math.sin(math.pi * progress ** 1.7)
        out.append((cx, cy, window,
                    _tilt_that_fits(cx, cy, window, wanted, width, height)))
    return out


def draw_zoom_frame(source, geometry):
    """One frame of a flight: crop, scale and tilt in a single affine resample.

    One pass rather than three. Cropping, then scaling, then rotating would resample the
    picture three times and soften it each time; here the only arithmetic between the board
    and the frame is a matrix of floats.
    """
    cx, cy, window, angle = geometry
    scale = window / WIDTH                          # board pixels per output pixel
    radians = math.radians(angle)
    cos, sin = math.cos(radians) * scale, math.sin(radians) * scale
    # Output (ox, oy) reads the board at centre + R(angle) . ((ox, oy) - centre of frame).
    matrix = (cos, -sin, cx - cos * (WIDTH / 2) + sin * (HEIGHT / 2),
              sin, cos, cy - sin * (WIDTH / 2) - cos * (HEIGHT / 2))
    return source.transform((WIDTH, HEIGHT), Image.AFFINE, matrix, Image.BICUBIC)


# Drawing a frame is 134 ms and the resample releases the interpreter lock, so the flights are
# drawn on several threads: 18 frames take 2.41 s on one and 0.53 s on six. Bilinear would
# also have been 2.4x faster but the frames end up a seven-fold enlargement of one cell, which
# is the one place in the video that cannot afford a softer resample.
ZOOM_WORKERS = max(1, min(6, (os.cpu_count() or 2)))


def zoom_frames(board_image, box, frames, into=True, spin=SPIN_DEGREES, workers=None):
    """The flight as raw RGB frames, in order, drawn ahead on several threads."""
    workers = workers or ZOOM_WORKERS
    geometry = zoom_geometry(box, frames, into, spin)
    with Image.open(board_image) as raw:
        source = raw.convert("RGB")
    draw = lambda g: draw_zoom_frame(source, g).tobytes()           # noqa: E731
    with ThreadPoolExecutor(workers) as pool:
        # In blocks, so the whole flight is not held in memory at once: a frame is 6 MB.
        for i in range(0, len(geometry), workers * 2):
            for data in pool.map(draw, geometry[i:i + workers * 2]):
                yield data
