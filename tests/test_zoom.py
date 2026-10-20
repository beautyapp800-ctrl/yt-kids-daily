"""The flight between the board and a cell. Run: python tests/test_zoom.py

What is checked here is what judder actually is - a velocity that changes direction from one
frame to the next - and the two joins either side of the flight, which are where a mistake
shows as a jump. The arithmetic is exact, so these are assertions about numbers rather than
about pictures; the comparison against the zoompan this replaced is in docs/zoom.md.
"""
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import grid

W, H = grid.WIDTH, grid.HEIGHT
FRAMES = 18


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def corners(cx, cy, window, angle):
    half_w, half_h = window / 2, window * H / W / 2
    cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return [(cx + dx * cos - dy * sin, cy + dx * sin + dy * cos)
            for dx, dy in ((-half_w, -half_h), (half_w, -half_h),
                           (-half_w, half_h), (half_w, half_h))]


def screen_x(box, geometry):
    """Where the cell's centre sits on screen, frame by frame."""
    centre = box[0] + box[2] / 2
    return [W * (centre - cx) / window + W / 2 for cx, _cy, window, _a in geometry]


def test_the_window_never_leaves_the_board():
    print("test_the_window_never_leaves_the_board")
    worst, where = None, None
    for count in range(18, 31):
        for index, box in enumerate(grid.layout(count)[4]):
            for into in (True, False):
                for frame in grid.zoom_geometry(box, FRAMES, into):
                    for px, py in corners(*frame):
                        margin = min(px, W - px, py, H - py)
                        if worst is None or margin < worst:
                            worst, where = margin, (count, index, into)
    check(worst >= -0.001, f"over every layout from 18 to 30 cells, every cell and both "
                           f"directions the worst margin is {worst:+.2f} px (at {where})")


def test_the_joins_either_side_are_exact():
    print("test_the_joins_either_side_are_exact")
    box = grid.layout(30)[4][7]
    first = grid.zoom_geometry(box, FRAMES, True)[0]
    last = grid.zoom_geometry(box, FRAMES, True)[-1]
    check(abs(first[0] - W / 2) < 1e-6 and abs(first[1] - H / 2) < 1e-6
          and abs(first[2] - W) < 1e-6,
          "the flight starts on exactly the whole board, so the hold before it cannot jump")
    x, y, w, h = box
    check(abs(last[0] - (x + w / 2)) < 1e-6 and abs(last[1] - (y + h / 2)) < 1e-6,
          "and lands on exactly the cell's centre")
    check(abs(last[2] - max(w, h * W / H)) < 1e-6,
          "filling the screen with the cell widened to 16:9, which is what the card that "
          "follows is")
    check(abs(first[3]) < 1e-9 and abs(last[3]) < 1e-9,
          "and the tilt is zero at both ends, so neither join is crooked")


def test_the_cell_never_doubles_back():
    print("test_the_cell_never_doubles_back")
    bad = []
    for count in range(18, 31):
        for index, box in enumerate(grid.layout(count)[4]):
            steps = [b - a for a, b in zip(screen_x(box, grid.zoom_geometry(box, FRAMES, True)),
                                           screen_x(box, grid.zoom_geometry(box, FRAMES, True))[1:])]
            if steps and max(steps) > 1 and min(steps) < -1:
                bad.append((count, index))
    check(not bad, f"no cell slides away from the middle before coming back ({len(bad)} would)")


def test_it_eases_in_and_out():
    print("test_it_eases_in_and_out")
    box = grid.layout(30)[4][7]
    windows = [g[2] for g in grid.zoom_geometry(box, FRAMES, True)]
    rate = [abs(b - a) for a, b in zip(windows, windows[1:])]
    middle = max(rate)
    check(rate[0] < middle / 5 and rate[-1] < middle / 5,
          f"the first and last frames move {rate[0]:.1f} and {rate[-1]:.1f} px against "
          f"{middle:.1f} at the quickest: it leaves slowly and settles")
    turns = sum(1 for a, b in zip(rate, rate[1:]) if (b - a) * (rate[1] - rate[0]) < 0)
    check(rate.index(middle) not in (0, len(rate) - 1),
          "and the quickest moment is in the middle of the flight, not at either end")


def test_no_frame_reverses_the_motion():
    print("test_no_frame_reverses_the_motion")
    # Judder is a velocity that changes sign frame to frame. The zoompan this replaced did
    # that 12 times in 15 chances; an eased flight turns once, at the top of the curve.
    worst = 0
    for count in range(18, 31):
        for box in grid.layout(count)[4]:
            for into in (True, False):
                pos = screen_x(box, grid.zoom_geometry(box, FRAMES, into))
                vel = [b - a for a, b in zip(pos, pos[1:])]
                acc = [b - a for a, b in zip(vel, vel[1:])]
                flips = sum(1 for a, b in zip(acc, acc[1:]) if a * b < 0)
                worst = max(worst, flips)
    check(worst <= 2, f"the worst flight changes direction of acceleration {worst} time(s); "
                      f"the zoompan did it 12 times in 15")


def test_out_is_in_run_backwards():
    print("test_out_is_in_run_backwards")
    box = grid.layout(24)[4][5]
    into = grid.zoom_geometry(box, FRAMES, True)
    out = grid.zoom_geometry(box, FRAMES, False)
    check(all(abs(a - b) < 1e-9 for p, q in zip(into, reversed(out)) for a, b in zip(p, q)),
          "the shrink is the grow played backwards, so a card leaves the way it arrived")


def test_it_renders_the_frames_it_promises():
    print("test_it_renders_the_frames_it_promises")
    from pipeline import render
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        board = tmp / "board.png"
        Image.new("RGB", (W, H), (200, 40, 90)).save(board)
        box = grid.layout(30)[4][7]
        clip = render._zoom_clip(board, box, 0.4, tmp / "flight.mp4", into=True)
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                              "-count_frames", "-show_entries",
                              "stream=nb_read_frames,width,height",
                              "-of", "default=nw=1:nk=1", str(clip)],
                             capture_output=True, text=True).stdout.split()
        check(out[:2] == [str(W), str(H)], f"the flight is {out[0]}x{out[1]}")
        check(int(out[2]) == 12, f"0.4 s at 30 fps is {out[2]} frames")
        # A flat board cannot show black corners from the tilt unless the window left it.
        frame = tmp / "mid.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-vf",
                        "select=eq(n\,8)", "-frames:v", "1", str(frame)], check=True)
        with Image.open(frame) as img:
            darkest = min(img.convert("L").getdata())
        check(darkest > 40, f"no black wedge anywhere in a mid-flight frame "
                            f"(darkest pixel {darkest})")


if __name__ == "__main__":
    test_the_window_never_leaves_the_board()
    test_the_joins_either_side_are_exact()
    test_the_cell_never_doubles_back()
    test_it_eases_in_and_out()
    test_no_frame_reverses_the_motion()
    test_out_is_in_run_backwards()
    test_it_renders_the_frames_it_promises()
    print("ALL ZOOM TESTS PASSED")
