"""The cover. Run: python tests/test_cover.py

Pictures are made in memory and measured: the board's size, what the title says, whether the
names under the cells are on or off, and that the frames chosen are not all one colour.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from pipeline import thumbnail as t


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def still(path, colour, subject_box=True):
    img = Image.new("RGB", (640, 360), colour)
    if subject_box:
        ImageDraw.Draw(img).ellipse([220, 100, 420, 280], fill=(250, 250, 250))
    img.save(path)
    return path


def candidates(tmp, subjects, colours=None):
    out = []
    for i, name in enumerate(subjects):
        colour = (colours or [(40, 150, 60)] * len(subjects))[i]
        out.append((name, still(tmp / f"{i}.jpg", colour), str(i)))
    return out


def test_the_title_is_number_theme_and_audience():
    print("test_the_title_is_number_theme_and_audience")
    check(t.title_text(1, "animals", 30) == ("30 ANIMALS", "for Kids"), "30 ANIMALS for Kids")
    check(t.title_text(1, "vehicles", 25) == ("25 VEHICLES", "for Kids"), "25 VEHICLES for Kids")
    check(t.title_text(1, "sea animals", 12)[0] == "12 SEA ANIMALS", "a single theme keeps its name")
    check(t.title_text(1, None, 9)[0].startswith("9 "), "and a missing theme does not crash")


def test_the_board_has_between_8_and_12_big_cells():
    print("test_the_board_has_between_8_and_12_big_cells")
    for available in (8, 9, 12, 30):
        cols, rows, boxes = t.layout(available, 200)
        check(8 <= len(boxes) <= 12, f"{available} available -> {len(boxes)} cells ({cols}x{rows})")
        check(min(w for _x, _y, w, _h in boxes) >= 150 and min(h for *_a, h in boxes) >= 100,
              "every cell is at least 150x100 at full size")
        for x, y, w, h in boxes:
            check(x - t.BORDER >= 0 and x + w + t.BORDER <= t.WIDTH
                  and y + h + t.BORDER <= t.HEIGHT, f"cell at ({x},{y}) is inside the picture") \
                if (x, y, w, h) == boxes[-1] else None
    try:
        t.layout(7, 200)
    except RuntimeError:
        check(True, "seven pictures are refused, not stretched over eight cells")
        return
    raise AssertionError("a board was built from seven pictures")


def test_a_cover_is_made_and_the_title_reads_at_feed_size():
    print("test_a_cover_is_made_and_the_title_reads_at_feed_size")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        names = ["cow", "pig", "lion", "tiger", "zebra", "horse", "sheep", "goat", "duck", "owl"]
        report = t.make(candidates(tmp, names), 3, "animals", 30, tmp / "out")
        with Image.open(report["path"]) as full, Image.open(report["small"]) as small:
            check(full.size == (1280, 720), f"full size is {full.size}")
            check(small.size == (210, 118), f"feed size is {small.size}")
        r = report["readability"]
        check(r["cap_px"] >= 11 and r["contrast"] >= 4.5 and r["ok"],
              f"title capital {r['cap_px']} px, letter against outline {r['contrast']}:1")
        check(8 <= report["cells"] <= 12, f"{report['cells']} cells")


def test_long_names_turn_the_labels_off_and_short_ones_may_not():
    print("test_long_names_turn_the_labels_off_and_short_ones_may_not")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        long = ["elephant", "butterfly", "helicopter", "motorcycle", "strawberry", "kangaroo",
                "flamingo", "dragonfly"]
        report = t.make(candidates(tmp, long), 1, "animals", 30, tmp / "long")
        check(not report["labels"], f"names like these would be {report['label_cap_if_drawn']} px "
                                    f"tall at 210x118 (need {t.MIN_SMALL_CAP_PX}): labels off")
        # The rule is the measurement, not the word count: whatever fits is judged by its size.
        size, cap = t.fit_labels([("ox", None, 0)] * 8, [(0, 0, 285, 235)] * 8)
        check(cap > 0 and size is not None, f"two-letter names fit at {size} px ({cap:.1f} px at feed size)")


def test_frames_are_not_all_one_colour():
    print("test_frames_are_not_all_one_colour")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        greens = [(30 + i, 160 + i, 50) for i in range(12)]
        reds = [(200, 30, 30), (230, 160, 20), (30, 60, 220), (160, 40, 200)]
        names = [f"g{i}" for i in range(12)] + [f"c{i}" for i in range(4)]
        cands = candidates(tmp, names, greens + reds)
        picked = [s for s, _p, _x in t.choose_frames(cands, 8)]
        colourful = [s for s in picked if s.startswith("c")]
        check(len(colourful) == 4, f"all four off-hue frames are in the eight ({picked})")


def test_black_bars_are_cropped_out_of_a_cell():
    print("test_black_bars_are_cropped_out_of_a_cell")
    img = Image.new("RGB", (640, 360), (0, 0, 0))
    img.paste(Image.new("RGB", (640, 240), (200, 120, 60)), (0, 60))
    cropped = t._without_bars(img)
    check(cropped.height == 240 and cropped.width == 640,
          f"a letterboxed frame comes back {cropped.size}, not 640x360")
    plain = Image.new("RGB", (640, 360), (60, 60, 60))
    check(t._without_bars(plain).size == (640, 360), "a plain dark frame is left alone")


if __name__ == "__main__":
    test_the_title_is_number_theme_and_audience()
    test_the_board_has_between_8_and_12_big_cells()
    test_a_cover_is_made_and_the_title_reads_at_feed_size()
    test_long_names_turn_the_labels_off_and_short_ones_may_not()
    test_frames_are_not_all_one_colour()
    test_black_bars_are_cropped_out_of_a_cell()
    print("ALL COVER TESTS PASSED")
