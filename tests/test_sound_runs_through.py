"""The audio stream must be as long as the picture. Run: python tests/test_sound_runs_through.py

This exists because of a real file: a six-and-a-half-minute video with a two-minute audio
stream. Nothing refused it - not the muxer, not ffprobe's format duration, which reports the
longest stream and so said 391 seconds - and a player shows the pictures to the end over
silence. Heard rather than seen, it reads as "the music stopped".
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.render import RenderError, check_sound_runs_the_whole_way, SOUND_SHORTFALL


def make(path, video_seconds, audio_seconds):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=blue:s=160x90:d={video_seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={audio_seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-t", str(max(video_seconds, audio_seconds)), str(path)],
        check=True, capture_output=True)
    return path


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def test_equal_lengths_pass(tmp):
    print("test_equal_lengths_pass")
    video, audio = check_sound_runs_the_whole_way(make(tmp / "equal.mp4", 4, 4))
    check(abs(video - audio) <= SOUND_SHORTFALL, f"4 s and 4 s accepted ({video:.2f}/{audio:.2f})")


def test_the_file_that_fooled_me_is_refused(tmp):
    print("test_the_file_that_fooled_me_is_refused")
    path = make(tmp / "short_audio.mp4", 10, 3)
    container = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=nw=1:nk=1", str(path)],
                               capture_output=True, text=True).stdout.strip()
    check(float(container) > 9, f"the container still claims {float(container):.1f} s, which "
                                "is why the container cannot be the thing that is checked")
    try:
        check_sound_runs_the_whole_way(path)
    except RenderError as e:
        check("silence" in str(e), f"refused, and says what a viewer would hear: {e}")
        return
    raise AssertionError("a video with 3 s of audio over 10 s of picture was accepted")


def test_a_rounding_difference_is_not_a_fault(tmp):
    print("test_a_rounding_difference_is_not_a_fault")
    # AAC frames are 1024 samples, so an audio stream lands a few hundredths short of the
    # video almost every time. Refusing that would refuse every correct render.
    check_sound_runs_the_whole_way(make(tmp / "rounding.mp4", 4, 3.98))
    check(True, "4.00 s of picture over 3.98 s of sound is accepted")


def test_a_silent_file_is_refused(tmp):
    print("test_a_silent_file_is_refused")
    path = tmp / "no_audio.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=160x90:d=3",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    str(path)], check=True, capture_output=True)
    try:
        check_sound_runs_the_whole_way(path)
    except RenderError as e:
        check("no video or no audio" in str(e), f"a video with no audio track at all: {e}")
        return
    raise AssertionError("a video with no audio stream was accepted")


def test_upload_refuses_it_too(tmp):
    print("test_upload_refuses_it_too")
    from pipeline import upload
    body = {"snippet": {"title": "t", "description": "d", "tags": ["a"]},
            "status": {"selfDeclaredMadeForKids": True}}
    bad = make(tmp / "upload_bad.mp4", 10, 3)
    problems = upload.check_metadata(body, bad, None)
    check(any("silence" in p for p in problems),
          f"the last gate before upload refuses it: {problems}")
    good = make(tmp / "upload_good.mp4", 4, 4)
    check(not upload.check_metadata(body, good, None), "and passes a sound one")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        test_equal_lengths_pass(tmp)
        test_the_file_that_fooled_me_is_refused(tmp)
        test_a_rounding_difference_is_not_a_fault(tmp)
        test_a_silent_file_is_refused(tmp)
        test_upload_refuses_it_too(tmp)
    print("ALL SOUND-LENGTH TESTS PASSED")
