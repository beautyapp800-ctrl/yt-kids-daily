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


def test_people_and_size_are_read_off_the_detector():
    print("test_people_and_size_are_read_off_the_detector")
    from core import vision
    boat = (0.30, 0.40, 0.70, 0.60)
    rower = (0.45, 0.42, 0.50, 0.55)                 # stands inside the boat's box
    visitor = (0.05, 0.70, 0.12, 0.98)               # stands at the glass, outside it
    facts = vision.frame_contents([("boat", 0.99, boat), ("person", 0.99, rower)], "")
    check(facts["people"] == 0, "the man rowing the boat belongs to the boat")
    check(abs(facts["subject_area"] - 0.08) < 1e-9, f"the boat fills {facts['subject_area']:.0%}")
    facts = vision.frame_contents([("bird", 0.92, boat), ("person", 0.97, visitor),
                                   ("person", 0.6, visitor)], "a dolphin, a woman, a building, a window")
    check(facts["people"] == 1, "a visitor outside the subject counts; an unsure one does not")
    check(facts["structures"] == ["building", "window"], f"built things: {facts['structures']}")
    penguins = vision.frame_contents([("person", 0.99, visitor)] * 12, "penguins, rocks, snow")
    check(penguins["people"] == 0 and penguins["people_detected"] == 12,
          "twelve 'people' the describer does not name are penguins, not people")
    check(vision.frame_contents([], "")["subject_area"] is None,
          "nothing recognised is unknown, not a subject filling 0% - a strawberry gets no box")


def test_what_keeps_a_frame_off_a_cover():
    print("test_what_keeps_a_frame_off_a_cover")
    check(t.unfit_for_cover("whale", {"people": 5, "structures": [], "subject_area": 0.3}),
          "people at an orca show")
    check(not t.unfit_for_cover("dolphin", {"people": 0, "structures": ["glass"], "subject_area": 0.2})
          and t.built_penalty("dolphin", {"structures": ["glass"]}) > 0,
          "aquarium glass behind an animal costs points but does not rule the frame out")
    check(not t.unfit_for_cover("boat", {"people": 1, "structures": [], "subject_area": 0.1}),
          "the man rowing the boat is part of the boat")
    check(not t.unfit_for_cover("jellyfish", {"people": 0, "structures": [], "subject_area": None}),
          "a frame the detector recognised nothing in is not called small")
    check(not t.unfit_for_cover("train", {"people": 0, "structures": ["building"],
                                          "subject_area": 0.3}),
          "a station behind a train is where a train belongs")
    check(t.unfit_for_cover("ladybug", {"people": 0, "structures": [], "subject_area": 0.001}),
          "a ladybug filling 0.1% of the frame is a speck: measured, not listed")
    check(not t.unfit_for_cover("ladybug", {"people": 0, "structures": [], "subject_area": 0.3}),
          "and a ladybug filling the frame is welcome")
    check(t.unfit_for_cover("lion", None) == "", "a clip never measured is not held against")


def test_unfit_frames_only_fill_in_when_there_are_not_enough():
    print("test_unfit_frames_only_fill_in_when_there_are_not_enough")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        names = [f"a{i}" for i in range(10)]
        cands = candidates(tmp, names, [(40 + 20 * i, 120, 200 - 15 * i) for i in range(10)])
        book = {n: {"clips": [{"id": str(i), "subject_area": 0.3, "people": 0,
                               "structures": []}]} for i, n in enumerate(names)}
        book["a0"]["clips"][0]["people"] = 3
        book["a1"]["clips"][0]["subject_area"] = 0.001
        picked = [s for s, _p, _x in t.choose_frames(cands, 8, book)]
        check("a0" not in picked and "a1" not in picked, f"both unfit frames left out: {picked}")
        picked = [s for s, _p, _x in t.choose_frames(cands[:8], 8, book)]
        check(len(picked) == 8, "with only eight to choose from, they fill the board anyway")


def test_subjects_from_recent_covers_go_to_the_back():
    print("test_subjects_from_recent_covers_go_to_the_back")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        names = [f"a{i}" for i in range(16)]
        cands = candidates(tmp, names, [(30 + 14 * i, 120, 220 - 12 * i) for i in range(16)])
        book = {n: {"clips": [{"id": str(i), "subject_area": 0.3, "people": 0,
                               "structures": []}]} for i, n in enumerate(names)}
        was_on = set(names[:6])
        picked = set(s for s, _p, _x in t.choose_frames(cands, 8, book, avoid=was_on))
        check(not (picked & was_on),
              f"none of the last cover's six subjects is used again: {sorted(picked)}")


def test_a_thin_theme_may_reuse_rather_than_leave_a_gap():
    print("test_a_thin_theme_may_reuse_rather_than_leave_a_gap")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        names = [f"b{i}" for i in range(9)]
        cands = candidates(tmp, names, [(30 + 20 * i, 120, 220 - 15 * i) for i in range(9)])
        book = {n: {"clips": [{"id": str(i), "subject_area": 0.3, "people": 0,
                               "structures": []}]} for i, n in enumerate(names)}
        picked = t.choose_frames(cands, 8, book, avoid=set(names[:7]))
        check(len(picked) == 8, "eight cells are filled even though only two subjects are free")


if __name__ == "__main__":
    test_the_title_is_number_theme_and_audience()
    test_the_board_has_between_8_and_12_big_cells()
    test_a_cover_is_made_and_the_title_reads_at_feed_size()
    test_long_names_turn_the_labels_off_and_short_ones_may_not()
    test_frames_are_not_all_one_colour()
    test_black_bars_are_cropped_out_of_a_cell()
    test_people_and_size_are_read_off_the_detector()
    test_what_keeps_a_frame_off_a_cover()
    test_unfit_frames_only_fill_in_when_there_are_not_enough()
    test_subjects_from_recent_covers_go_to_the_back()
    test_a_thin_theme_may_reuse_rather_than_leave_a_gap()
    print("ALL COVER TESTS PASSED")
