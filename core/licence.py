"""Read a file's licence from the page that hosts it, not from an aggregator's copy of it.

Openverse tells you the licence of a sound. For one track it was wrong: "Happy FROG" came back
as CC0 and the Freesound page it points to carries a CC BY-NC 4.0 licence. Non-commercial is
unusable on a monetised channel, and CC0 was exactly what had been asked for. An aggregator's
licence field is somebody's cached copy of the hosting site's licence, and it goes stale when an
uploader changes theirs, so for anything that goes into a public repository and a monetised
video the licence is read from the source.

Two sources cover everything this project uses:

  freesound.org   the sound's own page. A CC0 sound links the CC0 deed and no other licence;
                  anything else on the page is evidence against.
  wikimedia       the file page, through the API's extended metadata, which states the licence
                  short name for every file individually.

The answer is one of: "cc0", "pdm", "by", or something else spelled out. "unknown" means the
page could not be read, and unknown is treated as refusal by callers - a licence that cannot be
confirmed is not a licence.
"""
import re
import urllib.parse
import urllib.request

from core.logger import get_logger

log = get_logger("licence")

UA = "Mozilla/5.0 (yt-kids licence check; educational videos for children)"
CC_LICENCE = re.compile(r"creativecommons\.org/licenses/([a-z-]+)/([0-9.]+)")
CC_ZERO = re.compile(r"creativecommons\.org/publicdomain/zero/1\.0")


def _get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def freesound(page_url):
    """(licence, evidence) from a Freesound sound page."""
    try:
        html = _get(page_url)
    except Exception as e:                                       # noqa: BLE001
        return "unknown", f"page could not be read: {str(e)[:60]}"
    others = CC_LICENCE.findall(html)
    if CC_ZERO.search(html) and not others:
        return "cc0", "the page links the CC0 deed and no other licence"
    if others:
        kinds = sorted({k for k, _v in others})
        return "-".join(kinds), f"the page links {', '.join(f'{k} {v}' for k, v in sorted(set(others))[:3])}"
    return "unknown", "no licence link found on the page"


def wikimedia(file_title):
    """(licence, evidence) from Wikimedia Commons' own metadata for one file."""
    import json
    url = ("https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo"
           "&iiprop=extmetadata&format=json&titles=" + urllib.parse.quote(file_title))
    try:
        data = json.loads(_get(url))
    except Exception as e:                                       # noqa: BLE001
        return "unknown", f"metadata could not be read: {str(e)[:60]}"
    return _from_commons_pages(data)


def _from_commons_pages(data):
    for page in (data.get("query", {}).get("pages") or {}).values():
        meta = ((page.get("imageinfo") or [{}])[0].get("extmetadata") or {})
        short = (meta.get("LicenseShortName", {}).get("value") or "").lower()
        if "cc0" in short or "cc-zero" in short:
            return "cc0", f"Commons says: {short}"
        if "public domain" in short or short.startswith("pd"):
            return "pdm", f"Commons says: {short}"
        if short.startswith("cc by") and not any(x in short for x in ("nc", "nd", "sa")):
            return "by", f"Commons says: {short}"
        if short:
            return short.replace(" ", "-"), f"Commons says: {short}"
    return "unknown", "no licence in the file's metadata"


def wikimedia_by_pageid(page_id):
    """The same, for a Commons link of the form index.php?curid=NNN."""
    import json
    url = ("https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo"
           "&iiprop=extmetadata&format=json&pageids=" + str(page_id))
    try:
        data = json.loads(_get(url))
    except Exception as e:                                       # noqa: BLE001
        return "unknown", f"metadata could not be read: {str(e)[:60]}"
    return _from_commons_pages(data)


def verify(record):
    """Verify an Openverse record against its host. Returns (licence, evidence).

    The record's own `license` field is deliberately not consulted: this exists to check it.
    """
    page = str(record.get("page") or record.get("foreign_landing_url") or "")
    if "freesound.org" in page:
        return freesound(page)
    if "wikimedia.org" in page or "wikipedia.org" in page:
        match = re.search(r"curid=(\d+)", page)
        if match:
            return wikimedia_by_pageid(match.group(1))
        title = urllib.parse.unquote(page.rsplit("/", 1)[-1])
        if not title.startswith("File:"):
            title = "File:" + title
        return wikimedia(title)
    return "unknown", f"no verifier for {urllib.parse.urlparse(page).netloc or 'this host'}"


def usable(licence, allow_by=False):
    """CC0 and public domain always; plain attribution only when the caller can carry it."""
    return licence in ("cc0", "pdm") or (allow_by and licence == "by")
