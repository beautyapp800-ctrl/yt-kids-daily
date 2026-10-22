"""config.json, read once, with the fields the pipeline cannot run without checked up front.

Checked here rather than where each is used, because a missing field should stop a run before
it has spent a Neuron, not three stages in.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
OUTPUT_DIR = ROOT / "output"

REQUIRED = ["cards_per_video", "min_theme_cards", "card_seconds_min",
            "card_seconds_max", "voice",
            "rate_name", "rate_speech", "pitch_name", "pitch_speech",
            "publish_time", "publish_days_ahead", "timezone", "made_for_kids", "image_style"]


class ConfigError(Exception):
    pass


def load_config(path=None):
    path = Path(path or CONFIG_PATH)
    if not path.exists():
        raise ConfigError(f"{path} does not exist")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}") from e
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise ConfigError(f"config.json is missing: {', '.join(missing)}")
    if cfg.get("made_for_kids") is not True:
        # Not a preference. The channel is for children, so the law requires the flag, and a
        # config that says otherwise is a config that would get the channel in trouble.
        raise ConfigError("made_for_kids must be true: this channel is covered by COPPA")
    return cfg


def output_dir(video_id):
    out = Path(os.environ.get("KIDS_OUTPUT_DIR", OUTPUT_DIR)) / str(video_id)
    out.mkdir(parents=True, exist_ok=True)
    return out


def credentials():
    """(cloudflare account, cloudflare token, pixabay key) from the environment or .env."""
    values = {}
    for name in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "PIXABAY_API_KEY"):
        values[name] = os.environ.get(name)
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                k = k.strip()
                if k in values and not values[k]:
                    values[k] = v.strip().strip('"').strip("'")
    return (values["CLOUDFLARE_ACCOUNT_ID"], values["CLOUDFLARE_API_TOKEN"],
            values["PIXABAY_API_KEY"])
