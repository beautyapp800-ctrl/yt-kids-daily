"""The guessing game. Run: python tests/test_game.py

Offline: timings, wording, order, the riddle's choice between a piece and a blur, and the
levels of the effects against the voice after mixing. Pictures are made in memory.
"""
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageDraw

from pipeline import game


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def test_the_turn_keeps_the_asked_for_shape():
    print("test_the_turn_keeps_the_asked_for_shape")
    t = game.timeline(1.2, 1.6, has_sound=True)
    check(t["riddle"] == 0.5 and t["sound1"] == 0.5, "riddle and sound at 0.5")
    check(t["question"] == 2.5, "question at 2.5")
    check(t["countdown"] == 4.0, "countdown at 4.0, one number a second")
    check(t["reveal"] == 7.0, "reveal at 7.0")
    check(abs(t["answer"] - 7.3) < 1e-9, "the answer at 7.3")
    check(t["sound2"] == 9.5, "the sound again at 9.5")
    check(abs(t["end"] - 12.0) < 0.05, f"twelve seconds in all ({t['end']:.2f})")
    check(abs(t["end"] * game.FPS - round(t["end"] * game.FPS)) < 1e-6,
          "and a whole number of frames, so picture and sound stay together")


def test_a_long_question_pushes_the_countdown_instead_of_talking_over_it():
    print("test_a_long_question_pushes_the_countdown_instead_of_talking_over_it")
    t = game.timeline(2.0, 1.6, has_sound=True)
    check(t["countdown"] >= 2.5 + 2.0, f"a two-second question ends before the 3 ({t['countdown']:.2f})")
    long_answer = game.timeline(1.2, 2.8, has_sound=True)
    check(long_answer["sound2"] >= long_answer["answer"] + 2.8,
          "and a long answer pushes the second sound back")


def test_no_sound_question_without_a_sound():
    print("test_no_sound_question_without_a_sound")
    asked = [game.question_for(n, has_sound=False) for n in range(12)]
    check(game.SOUND_QUESTION not in asked, "\"Who makes this sound?\" is never asked of a silent turn")
    asked = [game.question_for(n, has_sound=True) for n in range(4)]
    check(len(set(asked)) == 4, f"with a sound all four wordings rotate: {asked}")


def test_answers_rotate_and_take_the_right_article():
    print("test_answers_rotate_and_take_the_right_article")
    check(game.answer_for(0, "lion") == "Yes! It's a lion!", game.answer_for(0, "lion"))
    check(game.answer_for(1, "elephant") == "That's right, an elephant!", game.answer_for(1, "elephant"))
    check(game.answer_for(2, "owl") == "Great job! An owl!", game.answer_for(2, "owl"))


def test_the_order_is_shuffled_stable_and_does_not_open_on_the_last_card():
    print("test_the_order_is_shuffled_stable_and_does_not_open_on_the_last_card")
    cards = [{"idx": i, "subject": f"s{i}"} for i in range(15)]
    a, b = game.order(cards, 7), game.order(cards, 7)
    check([c["idx"] for c in a] == [c["idx"] for c in b], "the same video plays the same order")
    check([c["idx"] for c in a] != list(range(15)), "it is not the learning order")
    for vid in range(1, 40):
        check(game.order(cards, vid)[0]["idx"] != 14, f"video {vid} does not open on the last card") \
            if vid in (1, 39) else None
        assert game.order(cards, vid)[0]["idx"] != 14


def _picture(kind):
    img = Image.new("RGB", (1920, 1080), (90, 150, 210))
    d = ImageDraw.Draw(img)
    if kind == "stripes":
        for x in range(640, 1280, 24):
            d.rectangle([x, 300, x + 11, 780], fill=(10, 10, 10))
            d.rectangle([x + 12, 300, x + 23, 780], fill=(250, 250, 250))
    return img


def test_a_detailed_middle_is_a_piece_and_an_empty_frame_is_a_blur():
    print("test_a_detailed_middle_is_a_piece_and_an_empty_frame_is_a_blur")
    box, score = game.choose_piece(_picture("stripes"))
    check(box is not None, f"stripes in the middle give a piece (detail {score})")
    x, y, w, h = box
    check(abs(w / h - 16 / 9) < 0.05 and abs(w - 1920 / game.PIECE_ZOOM) < 40,
          f"the piece is 16:9 and 1/{game.PIECE_ZOOM} of the frame ({w:.0f}x{h:.0f})")
    check(640 - 100 <= x + w / 2 <= 1280 + 100, "and it sits on the stripes")
    box, score = game.choose_piece(_picture("plain"))
    check(box is None, f"an empty sky gives the blur (detail {score})")
    box, _ = game.choose_piece(_picture("stripes"), subject_area=0.01)
    check(box is None, "and a subject the catalogue measured as a speck is blurred whatever "
                       "the texture says")


def test_the_reveal_is_smooth():
    print("test_the_reveal_is_smooth")
    box = game.choose_piece(_picture("stripes"))[0]
    frames = max(2, int(round(game.REVEAL_MOVE * game.FPS)))
    from pipeline import grid
    flight = grid.zoom_geometry(box, frames, into=False, spin=0.0)
    widths = [f[2] for f in flight]
    check(all(b >= a for a, b in zip(widths, widths[1:])), "the view only ever widens")
    steps = [b - a for a, b in zip(widths, widths[1:])]
    check(steps[0] < max(steps) / 3 and steps[-1] < max(steps) / 3,
          "it starts and finishes slowly - eased, not a jump")
    check(abs(widths[-1] - 1920) < 1e-6, "and lands on exactly the full frame")


def test_effects_are_under_the_voice_after_mixing():
    print("test_effects_are_under_the_voice_after_mixing")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        def tone(path, freq, seconds, amp):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            f"aevalsrc={amp}*sin({freq}*2*PI*t):d={seconds}:s=44100",
                            str(path)], check=True)
            return path

        voice = tone(tmp / "voice.wav", 300, 1.0, 0.2)
        loud_tick = tone(tmp / "tick.wav", 2000, 0.05, 0.9)
        voice_db = game.active_db(voice)
        game._LEVELS.clear()
        saved = game.sfx
        game.sfx = lambda name: loud_tick
        try:
            gain = game.effect_gain("tick", voice_db)
        finally:
            game.sfx = saved
            game._LEVELS.clear()
        mixed = game.mix([(voice, 0.0, 0.0), (loud_tick, 2.0, gain)], 3.0, tmp / "m.m4a")
        v = game.active_db(mixed, 0.1, 0.8)
        k = game.active_db(mixed, 2.0, 0.05)
        check(k < v, f"a tick recorded {game.active_db(loud_tick) - voice_db:+.1f} dB over the "
                     f"voice plays {k - v:+.1f} dB under it after mixing")
        check(abs((v - k) - game.UNDER_VOICE["tick"]) < 2.0,
              f"within 2 dB of the {game.UNDER_VOICE['tick']:.0f} dB asked for")


def test_mixing_does_not_change_the_length():
    print("test_mixing_does_not_change_the_length")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "s.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "aevalsrc=0.1*sin(440*2*PI*t):d=2:s=44100", str(src)], check=True)
        out = game.mix([(src, 11.0, 0.0)], 12.0, tmp / "m.m4a")
        seconds = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                        "format=duration", "-of", "default=nw=1:nk=1", str(out)],
                                       capture_output=True, text=True).stdout)
        check(abs(seconds - 12.0) < 0.06, f"a sound that runs past the end is cut at the turn's "
                                          f"length ({seconds:.3f} s)")


if __name__ == "__main__":
    test_the_turn_keeps_the_asked_for_shape()
    test_a_long_question_pushes_the_countdown_instead_of_talking_over_it()
    test_no_sound_question_without_a_sound()
    test_answers_rotate_and_take_the_right_article()
    test_the_order_is_shuffled_stable_and_does_not_open_on_the_last_card()
    test_a_detailed_middle_is_a_piece_and_an_empty_frame_is_a_blur()
    test_the_reveal_is_smooth()
    test_effects_are_under_the_voice_after_mixing()
    test_mixing_does_not_change_the_length()
    print("ALL GAME TESTS PASSED")
