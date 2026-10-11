"""Pictures from Cloudflare Workers AI, for the cards no footage covers.

Most cards are filmed. This is for the rest: a subject with no verified clip in the catalogue,
or one whose clip would not download. The style is the bright children's-book one from
config.image_style, and the prompt asks for one thing, large, on a plain background - the
opposite of a thumbnail composition, because here the subject IS the lesson and anything else
in the frame is something else for a three-year-old to look at.

The free allowance is 10,000 Neurons a day and an image is 96, so this is cheap - but it is
the only part of a daily run that spends any, which is why the catalogues exist and why a run
that needs a lot of drawings is a sign the clip catalogue needs filling, not that the
allowance needs raising.
"""
import base64
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from core.logger import get_logger

log = get_logger("images")

MODEL = "@cf/black-forest-labs/flux-1-schnell"
API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
STEPS = 4
ATTEMPTS = 3
TIMEOUT = 180

# What a second attempt could fix. A spent allowance or a rejected token answers the same way
# however many times it is asked.
_WORTH_RETRYING = re.compile(r"\b5\d\d\b|timed? ?out|timeout|connection|network", re.I)
_NOT_WORTH_RETRYING = re.compile(r"quota|allocation|neurons|auth|unauthor|forbidden", re.I)


class ImageError(Exception):
    pass


def _worth_asking_again(message):
    text = str(message)
    return bool(_WORTH_RETRYING.search(text)) and not _NOT_WORTH_RETRYING.search(text)


def draw(prompt, out_path, account, token, cfg=None, model=None, steps=None):
    """One image. Raises ImageError rather than leaving a broken file behind."""
    cfg = cfg or {}
    block = ((cfg.get("images") or {}).get("cloudflare")) or {}
    model = model or block.get("model", MODEL)
    steps = steps or block.get("steps", STEPS)
    url = API.format(account=account, model=model)
    body = json.dumps({"prompt": prompt, "steps": steps}).encode()

    last = None
    for attempt in range(1, ATTEMPTS + 1):
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:200]}"
        except urllib.error.URLError as e:
            last = f"network: {e.reason}"
        if attempt == ATTEMPTS or not _worth_asking_again(last):
            raise ImageError(last)
        wait = min(2 ** attempt, 20)
        log.warning("%s failed (%d/%d), waiting %ds: %s", model, attempt, ATTEMPTS, wait, last)
        time.sleep(wait)
    else:
        raise ImageError(last or "no answer")

    if not payload.get("success", True):
        raise ImageError(f"{model}: {payload.get('errors')}")
    encoded = (payload.get("result") or {}).get("image")
    if not encoded:
        raise ImageError(f"{model} returned no image: {str(payload)[:160]}")
    if encoded.startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    try:
        data = base64.b64decode(encoded)
    except Exception as e:                                       # noqa: BLE001
        raise ImageError(f"the image was not valid base64: {e}") from e
    if len(data) < 1000:
        raise ImageError(f"the image decoded to {len(data)} bytes")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return out_path
