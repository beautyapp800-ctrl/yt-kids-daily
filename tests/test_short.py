"""The daily Short. Run: python tests/test_short.py

Offline. What is checked is what YouTube and a viewer would see: made for kids, public with the
full video and not before, three turns with the real sound first, the picture never cut off the
edge of the frame, the riddle's window the picture's own shape, and a Short that cannot be
built costing the day nothing.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from pipeline import short


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def test_made_for_kids_and_public_with_its_video():
    print("test_made_for_kids_and_public_with_its_video")
    video = {"youtube_id": "abc", "published_at": "2026-11-02T14:00:00Z"}
    report = {"theme": "wild animals", "turns": [{}, {}, {}], "full_video_cards": 15}
    body = short.short_body(video, report, {"privacy_status": "private"})
    check(body["status"]["selfDeclaredMadeForKids"] is True, "made for kids, as COPPA requires")
    check(body["status"]["publishAt"] == video["published_at"],
          "public at the same moment as the full video, so its link never leads to a private one")
    check("https://youtu.be/abc" in body["snippet"]["description"], "it links the full video")
    title = body["snippet"]["title"]
    check(title == "Can You Guess These 3 Wild Animals? #shorts", f"title: {title}")
    check(len(title) <= 100, "inside YouTube's 100 characters")
    from pipeline import upload
    upload.assert_mandatory_flags(body)
    check(True, "and it passes the same COPPA assertion every upload passes")


def test_turns_with_a_real_sound_come_first():
    print("test_turns_with_a_real_sound_come_first")
    cards = [{"idx": i, "subject": f"s{i}", "sound_id": "x" if i in (2, 7, 11) else None}
             for i in range(15)]
    picked = short.choose_turns(cards, 1)
    check(len(picked) == 3, "three turns")
    check(all(c.get("sound_id") for _n, c in picked),
          "all three have a real sound - the channel's hook")
    few = [{"idx": i, "subject": f"s{i}", "sound_id": "x" if i == 4 else None} for i in range(15)]
    check(len(short.choose_turns(few, 1)) == 3, "with one sound, two silent turns fill the rest")


def _frame(subject_at):
    img = Image.new("RGB", (1920, 1080), (120, 160, 90))
    d = ImageDraw.Draw(img)
    for k in range(0, 300, 20):
        d.rectangle([subject_at - 150 + k, 300, subject_at - 140 + k, 800], fill=(10, 10, 10))
        d.rectangle([subject_at - 140 + k, 300, subject_at - 130 + k, 800], fill=(250, 240, 220))
    return img


def test_the_slice_follows_the_subject_and_stays_in_the_frame():
    print("test_the_slice_follows_the_subject_and_stays_in_the_frame")
    for at in (300, 960, 1600):
        x0 = short.slice_left(_frame(at))
        check(0 <= x0 <= 1920 - short.SLICE_W, f"subject at {at}: slice {x0}-{x0 + short.SLICE_W} "
                                              "inside the frame")
        check(x0 <= at - 150 or x0 == 0, f"and the subject's left edge is in it")
        check(x0 + short.SLICE_W >= at + 150 or x0 == 1920 - short.SLICE_W,
              "and its right edge too - the wolf's head was a sliver at the edge once")


def test_the_riddle_window_is_the_picture_s_own_shape():
    print("test_the_riddle_window_is_the_picture_s_own_shape")
    still = _frame(960).crop((528, 0, 1392, 1080)).resize((short.PIC_W, short.PIC_H))
    box, score = short.piece_in_slice(still)
    check(box is not None, f"a striped middle gives a piece (detail {score})")
    x, y, w, h = box
    check(abs(w / h - short.PIC_W / short.PIC_H) < 0.03, f"4:5 like the picture ({w:.0f}x{h:.0f})")
    check(x >= 0 and y >= 0 and x + w <= short.PIC_W + 1 and y + h <= short.PIC_H + 1,
          "inside the picture")
    plain = Image.new("RGB", (short.PIC_W, short.PIC_H), (90, 150, 210))
    check(short.piece_in_slice(plain)[0] is None, "an empty picture gives the blur")


def test_a_short_that_cannot_be_made_costs_the_day_nothing():
    print("test_a_short_that_cannot_be_made_costs_the_day_nothing")

    class FakeDb:
        events = []

        def get_video(self, _vid):
            return {"youtube_id": None}

        def log_event(self, vid, stage, level, msg):
            self.events.append((stage, level, msg))

    db = FakeDb()
    with tempfile.TemporaryDirectory() as tmp:
        ok = short.run(1, {"shorts": True}, db, Path(tmp))
    check(ok is True, "the stage still reports success, so the video's run is not failed")
    check(any(level == "warning" and "no Short today" in msg for _s, level, msg in db.events),
          "and the reason is recorded for the email")


def test_the_new_column_can_be_written():
    print("test_the_new_column_can_be_written")
    from core import db
    check("short_youtube_id" in db._VIDEO_FIELDS
          and any(c == "short_youtube_id" for _t, c, _d in db._MIGRATIONS),
          "videos.short_youtube_id is migrated and writable")


if __name__ == "__main__":
    test_made_for_kids_and_public_with_its_video()
    test_turns_with_a_real_sound_come_first()
    test_the_slice_follows_the_subject_and_stays_in_the_frame()
    test_the_riddle_window_is_the_picture_s_own_shape()
    test_a_short_that_cannot_be_made_costs_the_day_nothing()
    test_the_new_column_can_be_written()
    print("ALL SHORT TESTS PASSED")
