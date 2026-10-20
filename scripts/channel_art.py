"""Draw the channel's avatar and banner, in the covers' style.

    python scripts/channel_art.py

Writes assets/channel/avatar.png (800x800), banner.png (2560x1440) and previews at the sizes
people really see them: the avatar at 98 and 36 px, the banner as a phone shows it.

The avatar is drawn from shapes only, with no footage in it. Pixabay's licence allows its
pictures in videos and thumbnails but not "as part of a trademark, design mark, trade name ...
or logo", and a channel avatar is a logo. It is the board in miniature - coloured cells filling
up with green ticks - which is what every video is, and which still reads at 36 px where any
word would not.

The banner may use frames, as the covers do. Everything that has to be read is inside the
1546x423 centre that YouTube shows on a phone; the frames run out to the edges for desktop and
TV, where more of the banner is visible.
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFilter

from pipeline import grid, thumbnail as t

OUT = ROOT / "assets" / "channel"
NAME = "Moo Toot"
TAGLINE = "Real animals  •  Real sounds  •  First words"
BANNER = (2560, 1440)
SAFE = (1546, 423)
PHONE_WIDTH = 375          # how wide a phone shows the safe area, in CSS pixels


def _wash(size, top, bottom, rays_at=(0.5, 0.5), rays=20, alpha=34):
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = y / max(h - 1, 1)
        d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * k) for a, b in zip(top, bottom)))
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    cx, cy = w * rays_at[0], h * rays_at[1]
    far = max(w, h) * 1.6
    step = 360 / rays
    for i in range(rays):
        a0, a1 = math.radians(i * step), math.radians(i * step + step / 2)
        ld.polygon([(cx, cy), (cx + far * math.cos(a0), cy + far * math.sin(a0)),
                    (cx + far * math.cos(a1), cy + far * math.sin(a1))],
                   fill=(255, 255, 255, alpha))
    return Image.alpha_composite(img.convert("RGBA"), layer.filter(ImageFilter.GaussianBlur(4)))


def avatar(size=800):
    """A 3x3 board of rainbow cells on a blue sunburst, ticks on the first row and a big one
    in the middle. Kept well inside the circle YouTube crops it to."""
    _n, top, bottom, _a = t.PALETTES[0]
    img = _wash((size, size), top, bottom)
    d = ImageDraw.Draw(img)
    inner = size * 0.60                     # the board, inside the circle with room to spare
    gap = inner * 0.06
    cell = (inner - 2 * gap) / 3
    x0 = y0 = (size - inner) / 2
    shadow = Image.new("L", img.size, 0)
    sd = ImageDraw.Draw(shadow)
    for i in range(9):
        r, c = divmod(i, 3)
        x, y = x0 + c * (cell + gap), y0 + r * (cell + gap)
        sd.rounded_rectangle([x, y + size * 0.012, x + cell, y + cell + size * 0.012],
                             radius=cell * 0.24, fill=255)
    img.paste(Image.new("RGBA", img.size, (0, 20, 60, 255)), (0, 0),
              shadow.filter(ImageFilter.GaussianBlur(size * 0.01)).point(lambda p: int(p * 0.5)))
    d = ImageDraw.Draw(img)
    for i in range(9):
        r, c = divmod(i, 3)
        x, y = x0 + c * (cell + gap), y0 + r * (cell + gap)
        d.rounded_rectangle([x, y, x + cell, y + cell], radius=cell * 0.24,
                            fill=grid.cell_colour(i, 9), outline=(255, 255, 255),
                            width=max(3, round(size * 0.012)))
    for i in (0, 1, 2):                     # the first row done: the board filling up
        r, c = divmod(i, 3)
        badge = grid.tick_badge(round(cell * 0.62))
        x, y = x0 + c * (cell + gap), y0 + r * (cell + gap)
        img.alpha_composite(badge, (round(x + (cell - badge.width) / 2),
                                    round(y + (cell - badge.height) / 2)))
    big = grid.tick_badge(round(size * 0.30))
    img.alpha_composite(big, (round(size * 0.60), round(size * 0.58)))
    circle = Image.new("L", (size, size), 0)
    ImageDraw.Draw(circle).ellipse([0, 0, size - 1, size - 1], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), circle)
    return img.convert("RGB"), out


def _stills():
    """Frames for the banner: one per subject from the catalogue, chosen by the covers' own
    rule, so the frames the covers would refuse - people at an orca show, a ladybug that is a
    speck - are refused here too."""
    from pipeline import catalogue
    book = catalogue.load()
    frames = ROOT / "data" / "candidate-frames"
    candidates = []
    # Animals and vehicles only: the tagline says "real animals", and the food clips are where
    # the detector misses most - a hand with a knife at the edge of a chopping board.
    for subject, entry in sorted(book.items()):
        if t._theme_of(subject) == "fruit and vegetables":
            continue
        for clip in entry.get("clips", []):
            path = frames / f"{subject.replace(' ', '_')}_{clip['id']}.jpg"
            if path.exists() and not t.unfit_for_cover(subject, clip):
                candidates.append((subject, path, clip["id"]))
                break
    return [p for _s, p, _x in t.choose_frames(candidates, 16, book)]


def banner():
    w, h = BANNER
    _n, top, bottom, accent = t.PALETTES[0]
    img = _wash(BANNER, top, bottom, rays_at=(0.5, 0.5), rays=24, alpha=30).convert("RGB")
    sx, sy = (w - SAFE[0]) // 2, (h - SAFE[1]) // 2

    # Frames in two bands above and below the safe area: TV and desktop show them, a phone
    # does not, and nothing on them needs to be read.
    frames = _stills()
    if frames:
        cw, ch = 300, 200
        for band, y in enumerate((sy - ch - 70, sy + SAFE[1] + 70)):
            n = (w + 40) // (cw + 40) + 1
            for i in range(n):
                x = -60 + i * (cw + 40) + (band * (cw + 40) // 2)
                path = frames[(i + band * 7) % len(frames)]
                tile = Image.new("RGB", (cw + 24, ch + 24), grid.cell_colour(i + band, 9))
                tile.paste(t._cover_crop(path, cw, ch), (12, 12))
                mask = Image.new("L", tile.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle([0, 0, tile.width - 1, tile.height - 1],
                                                       radius=28, fill=255)
                img.paste(tile, (x, y), mask)

    # The safe area: a dark rounded plate so the words read over anything, then the words.
    plate = Image.new("L", BANNER, 0)
    ImageDraw.Draw(plate).rounded_rectangle([sx + 20, sy + 10, sx + SAFE[0] - 20,
                                             sy + SAFE[1] - 10], radius=60, fill=255)
    img.paste(Image.new("RGB", BANNER, (10, 40, 120)), (0, 0),
              plate.point(lambda p: int(p * 0.55)))
    d = ImageDraw.Draw(img)
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    size = 260
    while size > 60:
        box = probe.textbbox((0, 0), NAME, font=t._font(size), stroke_width=16)
        if box[2] - box[0] <= SAFE[0] - 520 and box[3] - box[1] <= SAFE[1] * 0.58:
            break
        size -= 4
    name_font = t._font(size)
    box = probe.textbbox((0, 0), NAME, font=name_font, stroke_width=16)
    tw, th = box[2] - box[0], box[3] - box[1]
    tick = grid.tick_badge(round(th * 0.95))
    gap = 40
    total = tw + gap + tick.width
    left = (w - total) // 2
    ny = sy + 40 - box[1]
    d.text((left - box[0], ny), NAME, font=name_font, fill=accent, stroke_width=16,
           stroke_fill=t.OUTLINE)
    img.paste(tick, (left + tw + gap, sy + 40 + (th - tick.height) // 2), tick)

    tsize = 110
    while tsize > 30:
        tb = probe.textbbox((0, 0), TAGLINE, font=t._font(tsize), stroke_width=8)
        if tb[2] - tb[0] <= SAFE[0] - 120:
            break
        tsize -= 2
    tf = t._font(tsize)
    tb = probe.textbbox((0, 0), TAGLINE, font=tf, stroke_width=8)
    d.text(((w - (tb[2] - tb[0])) // 2 - tb[0], sy + SAFE[1] - 40 - tb[3]), TAGLINE, font=tf,
           fill=(255, 255, 255), stroke_width=8, stroke_fill=t.OUTLINE)

    scale = PHONE_WIDTH / SAFE[0]
    cap = lambda f: (f.getbbox("H")[3] - f.getbbox("H")[1]) * scale     # noqa: E731
    return img, {"name_px_on_phone": round(cap(name_font), 1),
                 "tagline_px_on_phone": round(cap(tf), 1),
                 "safe_area": (sx, sy, sx + SAFE[0], sy + SAFE[1])}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    square, round_ = avatar()
    square.save(OUT / "avatar.png")
    for px in (98, 36):
        prev = Image.new("RGB", (px + 20, px + 20), (255, 255, 255))
        prev.paste(round_.resize((px, px), Image.LANCZOS), (10, 10),
                   round_.resize((px, px), Image.LANCZOS))
        prev.save(OUT / f"avatar_preview_{px}.png")

    img, report = banner()
    img.save(OUT / "banner.jpg", quality=92)
    sx, sy, ex, ey = report["safe_area"]
    phone = img.crop((sx, sy, ex, ey)).resize((PHONE_WIDTH, round(SAFE[1] * PHONE_WIDTH / SAFE[0])),
                                               Image.LANCZOS)
    phone.save(OUT / "banner_preview_phone.png")
    guide = img.copy()
    ImageDraw.Draw(guide).rectangle(report["safe_area"], outline=(255, 0, 0), width=6)
    guide.resize((1280, 720), Image.LANCZOS).save(OUT / "banner_preview_safe_area.jpg", quality=88)
    size = (OUT / "banner.jpg").stat().st_size
    print(f"avatar 800x800, banner 2560x1440 ({size / 1048576:.1f} MB, YouTube allows 6)")
    print(f"on a phone ({PHONE_WIDTH} px across the safe area): name capital "
          f"{report['name_px_on_phone']} px, tagline capital {report['tagline_px_on_phone']} px")


if __name__ == "__main__":
    main()
