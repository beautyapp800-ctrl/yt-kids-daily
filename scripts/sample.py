"""Cut a small excerpt of a finished video, and prove the excerpt is sound before sending it.

    python scripts/sample.py output/7/final.mp4 --seconds 120

Written after an excerpt was sent that had six and a half minutes of pictures over two minutes
of audio. The cause was `-t` placed before `-i`: with a filter chain in play this build of
ffmpeg applied it to the audio only and let the video run to the end. So `-t` goes after the
input here, where it is an output option and limits every stream, and the result is measured
rather than assumed - the same rule the pipeline itself now follows.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.render import check_sound_runs_the_whole_way


def cut(source, seconds=120, start=0, width=960, crf=31, out=None):
    source = Path(source)
    out = Path(out) if out else source.with_name(f"sample_{seconds}s.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start), "-i", str(source),
         "-t", str(seconds),                      # after -i: applies to every output stream
         "-vf", f"scale={width}:-2", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", str(crf), "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
         str(out), "-loglevel", "error"],
        check=True)
    video_seconds, audio_seconds = check_sound_runs_the_whole_way(out)
    return out, video_seconds, audio_seconds


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    out, video_seconds, audio_seconds = cut(args.source, args.seconds, args.start,
                                            args.width, out=args.out)
    print(f"{out}  {out.stat().st_size / 1048576:.1f} MB  "
          f"picture {video_seconds:.1f} s, sound {audio_seconds:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
