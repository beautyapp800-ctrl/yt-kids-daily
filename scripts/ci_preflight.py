"""Checks a CI run can succeed, before it spends anything.

    python scripts/ci_preflight.py

Runs first in the workflow and exits non-zero with a plain explanation if something that would
fail the run later is already wrong. Each check is here because skipping it costs a day:

- the YouTube token is set and loads and refreshes. This is the one secret that ends the whole
  channel when it goes, and it costs no API quota to try.
- ffmpeg and ffprobe are on the PATH.
- edge-tts can actually speak from this machine. Microsoft's free endpoint refuses some
  datacentre addresses, and a GitHub runner is one.
- the made-for-kids guard holds: config.json says so, and the upload module's constant agrees.
  A config that says otherwise is a channel in trouble, so it stops the run before anything is
  rendered.
- a clip from the catalogue can really be fetched from this machine, because the footage comes
  off Pixabay's CDN and nothing in a laptop test shows whether a runner is allowed to.

CLOUDFLARE_* is deliberately NOT required: it is only touched when a card has no footage and
has to be drawn, and a run with a good catalogue never needs it.

Findings are left in preflight-problems.txt so the email can say which check failed instead of
listing everything it could have been. It never prints a secret, only whether it is set.
"""
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PROBLEMS_PATH = ROOT / "preflight-problems.txt"


def main():
    import shutil
    problems = []

    token_set = bool(os.environ.get("YOUTUBE_TOKEN_JSON"))
    print(f"secrets: YOUTUBE_TOKEN_JSON={'set' if token_set else 'MISSING'}, "
          f"CLOUDFLARE_ACCOUNT_ID={'set' if os.environ.get('CLOUDFLARE_ACCOUNT_ID') else 'not set'}, "
          f"CLOUDFLARE_API_TOKEN={'set' if os.environ.get('CLOUDFLARE_API_TOKEN') else 'not set'}"
          " (the Cloudflare pair is optional)")
    if not token_set:
        problems.append("secrets not set in this workflow: YOUTUBE_TOKEN_JSON")

    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        print(f"{tool}: {found or 'MISSING'}")
        if not found:
            problems.append(f"{tool} is not installed on this runner")

    try:
        from core.config import load_config
        cfg = load_config()
        print("config: loads, made_for_kids is true")
        import pipeline.upload as upload
        if upload.MADE_FOR_KIDS is not True:
            problems.append("pipeline/upload.py does not declare the video as made for kids")
    except Exception as e:                                       # noqa: BLE001
        print(f"config: FAILED: {e}")
        problems.append(f"the config does not pass its own check: {e}")
        cfg = {}

    try:
        from core import tts
        with tempfile.TemporaryDirectory() as tmp:
            tts.speak("This is a short test of the narrator's voice.",
                      Path(tmp) / "preflight.mp3", cfg.get("voice", tts.DEFAULT_VOICE),
                      "-10%", "+0Hz")
        print("edge-tts: spoke a test sentence")
    except Exception as e:                                       # noqa: BLE001
        print(f"edge-tts: FAILED: {e}")
        problems.append(f"edge-tts cannot speak from this machine: {e}. If this is a 403, "
                        "Microsoft is refusing the runner's address.")

    try:
        from pipeline import catalogue
        book = catalogue.load()
        sample = next((c["clip"] for v in book.values() for c in v.get("clips", [])
                       if c.get("clip")), None)
        if not sample:
            problems.append("the clip catalogue is empty; run scripts/build_catalogue.py")
        else:
            req = urllib.request.Request(sample, headers={"User-Agent": "yt-kids/0.1",
                                                          "Range": "bytes=0-2047"})
            with urllib.request.urlopen(req, timeout=40) as resp:
                got = len(resp.read(2048))
            print(f"clip CDN: fetched {got} bytes of a catalogue clip")
    except Exception as e:                                       # noqa: BLE001
        print(f"clip CDN: FAILED: {e}")
        problems.append(f"a catalogue clip cannot be fetched from this machine (stock site "
                        f"refused or unreachable): {str(e)[:120]}")

    if token_set:
        try:
            from core import youtube
            creds = youtube.load_credentials()
            print(f"youtube token: loads and refreshes (valid={creds.valid})")
        except Exception as e:                                   # noqa: BLE001
            print(f"youtube token: FAILED: {e}")
            problems.append(f"the YouTube token does not work: {e}")

    try:
        PROBLEMS_PATH.write_text("\n".join(problems), encoding="utf-8")
    except OSError as e:                                         # noqa: BLE001
        print(f"(could not write {PROBLEMS_PATH}: {e})")

    if problems:
        print("\nPREFLIGHT FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\npreflight ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
