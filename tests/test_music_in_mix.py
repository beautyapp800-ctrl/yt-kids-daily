"""The music has to be in the finished video. Run: python tests/test_music_in_mix.py

Written after video 1 was published with no music at all. The cause was a blanket *.mp3 in
.gitignore, so the runner checked out a repository with an empty music folder; the render had
a branch that skipped the bed when there was no track and logged nothing, so nothing in the
pipeline, the log or the summary email said a word about it.

Two things are checked here: that a missing track stops the render instead of passing quietly,
and that the measurement can tell a mix with a bed from one without.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import music
from pipeline import render


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def speech_like(path, seconds=24):
    """A voice track: a tone for a second, then a second of near-silence, repeated. The quiet
    seconds are the gaps a bed would fill."""
    parts = "+".join(f"0.3*sin(900*2*PI*t)*between(mod(t\,2)\,0\,0.8)" for _ in range(1))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"aevalsrc={parts}:d={seconds}:s=44100", "-c:a", "aac", str(path)],
                   check=True)
    return path


def bed_like(path, seconds=24, level=0.03):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"aevalsrc={level}*sin(220*2*PI*t):d={seconds}:s=44100",
                    "-c:a", "aac", str(path)], check=True)
    return path


def mix(voice, bed, out):
    args = ["ffmpeg", "-y", "-v", "error", "-i", str(voice)]
    if bed:
        args += ["-i", str(bed), "-filter_complex",
                 "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]", "-map", "[a]"]
    args += ["-c:a", "aac", str(out)]
    subprocess.run(args, check=True)
    return out


def test_a_mix_with_a_bed_passes_and_one_without_fails(tmp):
    print("test_a_mix_with_a_bed_passes_and_one_without_fails")
    voice = speech_like(tmp / "voice.m4a")
    bed = bed_like(tmp / "bed.m4a")
    heard = render.check_music_is_audible(voice, mix(voice, bed, tmp / "with.m4a"))
    check(heard["lift_db"] >= render.MUSIC_IN_GAPS_DB,
          f"a real bed lifts the quiet seconds by {heard['lift_db']} dB")
    try:
        render.check_music_is_audible(voice, mix(voice, None, tmp / "without.m4a"))
    except render.RenderError as e:
        check("not in the mix" in str(e), f"and no bed is refused: {str(e)[:90]}")
        return
    raise AssertionError("a mix with no music at all was accepted")


def test_a_bed_that_stops_halfway_is_caught(tmp):
    print("test_a_bed_that_stops_halfway_is_caught")
    voice = speech_like(tmp / "voice2.m4a", 40)
    half = bed_like(tmp / "half.m4a", 20)
    padded = tmp / "halfpad.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(half), "-af", "apad=whole_dur=40",
                    "-c:a", "aac", str(padded)], check=True)
    try:
        render.check_music_is_audible(voice, mix(voice, padded, tmp / "stops.m4a"))
    except render.RenderError as e:
        check("halves" in str(e), f"a bed that stops in the middle is refused: {str(e)[:100]}")
        return
    raise AssertionError("a bed that stopped halfway through was accepted")


def test_an_empty_music_folder_stops_the_render(tmp):
    print("test_an_empty_music_folder_stops_the_render")
    empty = tmp / "nothing"
    empty.mkdir()
    check(music.pick(1, empty) is None, "no track is found in an empty folder")
    source = (ROOT / "pipeline" / "render.py").read_text(encoding="utf-8")
    check("raise RenderError(" in source.split("chosen = music or music_lib.pick")[1][:600],
          "and the render raises instead of carrying on without a bed")


def test_the_tracks_are_in_the_repository():
    print("test_the_tracks_are_in_the_repository")
    listed = subprocess.run(["git", "ls-files", "assets/music"], cwd=ROOT,
                            capture_output=True, text=True).stdout.split()
    audio = [f for f in listed if f.lower().endswith((".mp3", ".ogg", ".wav", ".m4a"))]
    check(audio, f"the tracks are committed, not just on this machine: {audio}")
    check(len(audio) == len(music.tracks()),
          f"every track on disk is in the repository ({len(audio)} of {len(music.tracks())})")


def test_the_effects_are_in_the_repository():
    print("test_the_effects_are_in_the_repository")
    listed = subprocess.run(["git", "ls-files", "assets/sfx"], cwd=ROOT,
                            capture_output=True, text=True).stdout.split()
    for name in ("pop", "whoosh", "tick", "sting"):
        check(f"assets/sfx/{name}.wav" in listed, f"{name}.wav is committed, not only on disk")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        test_a_mix_with_a_bed_passes_and_one_without_fails(tmp)
        test_a_bed_that_stops_halfway_is_caught(tmp)
        test_an_empty_music_folder_stops_the_render(tmp)
        test_the_tracks_are_in_the_repository()
        test_the_effects_are_in_the_repository()
    print("ALL MUSIC-IN-MIX TESTS PASSED")
