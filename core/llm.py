"""Text from Cloudflare Workers AI, so the project needs no language-model key of its own.

yt-factory uses Groq. This one does not, deliberately: it already has a Cloudflare account and
token for the pictures and the frame checking, and one fewer secret is one fewer thing to
rotate, leak or forget. The 70b model is used because the writing here is short and the
difference shows - asked for a fact about a whale, the 8b model said whales "can jump all the
way out of the water", which is a leap for a three-year-old to picture, while the 70b said
they are "really big animals that live in the ocean".
"""
import json
import re
import time
import urllib.error
import urllib.request

from core.logger import get_logger

log = get_logger("llm")

MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
RETRIES = 4
TIMEOUT = 120


class LLMError(Exception):
    pass


class QuotaExhausted(LLMError):
    """The daily free allocation is spent. Retrying cannot help and costs a minute each time,
    so callers that loop - the catalogue builders - stop on this instead of grinding through
    four waits per candidate and then recording every subject as having nothing."""


def complete(prompt, system, account, token, model=MODEL, max_tokens=400, temperature=0.8):
    """One answer, as text. Retries a throttle or a gateway error, nothing else."""
    url = API.format(account=account, model=model)
    body = json.dumps({"messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": prompt}],
                       "max_tokens": max_tokens, "temperature": temperature}).encode()
    last = None
    for attempt in range(1, RETRIES + 1):
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            detail = e.read()[:300]
            last = LLMError(f"HTTP {e.code}: {detail[:200]}")
            if e.code == 429 and (b"daily free allocation" in detail or b"neurons" in detail):
                raise QuotaExhausted(f"HTTP 429: {detail[:160]}") from e
            if e.code not in (429, 500, 502, 503, 504):
                raise last from e
        except urllib.error.URLError as e:
            last = LLMError(f"network: {e.reason}")
        wait = min(2 ** attempt, 20)
        log.warning("%s failed (%d/%d), waiting %ds: %s", model, attempt, RETRIES, wait, last)
        time.sleep(wait)
    else:
        raise last or LLMError("no answer")

    if not payload.get("success", True):
        raise LLMError(f"{model}: {payload.get('errors')}")
    text = (payload.get("result") or {}).get("response")
    if not text:
        raise LLMError(f"{model} returned no text: {str(payload)[:160]}")
    return str(text).strip()


def complete_json(prompt, system, account, token, **kw):
    """The same, parsed as JSON.

    Models wrap JSON in prose and in code fences however firmly they are told not to, so the
    outermost braces are taken rather than the whole reply trusted.
    """
    raw = complete(prompt, system + "\n\nReply with JSON and nothing else.",
                   account, token, **kw)
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise LLMError(f"no JSON in the reply: {raw[:160]}")
    blob = text[start:end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        pass
    # Llama answers with a Python dict about one time in five - single quotes, True, None -
    # which is a formatting habit rather than a refusal, and throwing the whole answer away
    # over a quote mark would cost an attempt for nothing. literal_eval reads that and
    # executes nothing, so a reply that is neither JSON nor a literal still raises.
    try:
        import ast
        value = ast.literal_eval(blob)
        if isinstance(value, (dict, list)):
            return value
        raise LLMError(f"the reply parsed to a {type(value).__name__}, not an object")
    except (ValueError, SyntaxError) as e:
        raise LLMError(f"the reply was not valid JSON ({e}): {raw[:160]}") from e
