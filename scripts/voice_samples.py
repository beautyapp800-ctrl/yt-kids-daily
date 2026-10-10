"""Three 30-second samples in three voices, for a person to choose between.

    python scripts/voice_samples.py

Same words, same pauses, same rate in all three, so what is being compared is the voice and
nothing else. The cards are real ones from the subject list, in the real shape: the name on
its own, a long gap for the child to repeat it, then one short fact.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import tts

VOICES = [
    ("en-US-AvaNeural", "expressive, caring, warm"),
    ("en-US-EmmaNeural", "cheerful, clear, bright"),
    ("en-US-JennyNeural", "friendly, gentle, comforting"),
]

CARDS = [
    ("Whale", "The blue whale is bigger than a bus."),
    ("Octopus", "An octopus has three hearts."),
    ("Tractor", "A tractor pulls heavy things on the farm."),
    ("Butterfly", "A butterfly tastes with its feet."),
]

OUT = ROOT / "output" / "voice-samples"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    for voice, described in VOICES:
        short = voice.split("-")[2].replace("Neural", "")
        parts = []
        for i, (name, fact) in enumerate(CARDS):
            parts.append(tts.card_audio(name, fact, OUT / f"_{short}_{i}.mp3", cfg,
                                        voice=voice, work=OUT / "_parts"))
        final = OUT / f"sample-{short.lower()}.mp3"
        tts.join(parts, final)
        print(f"{short:6} {tts.duration(final):5.1f}s  {described:30} {final}")
        for p in parts:
            Path(p).unlink(missing_ok=True)
    print(f"\nrate {cfg['voice_rate']}, pauses {cfg['pause_before_name_ms']}/"
          f"{cfg['pause_after_name_ms']}/{cfg['pause_between_cards_ms']} ms "
          f"(before the name / after it / between cards)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
