"""Offline tests for reading a licence at its source. Run: python tests/test_licence.py

The page is replaced by canned HTML. What is tested is the judgement made about it, because
that is where the one real failure was: Openverse called "Happy FROG" CC0 and the Freesound
page it points to said CC BY-NC.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.logger
core.logger.LOG_DIR = Path(tempfile.mkdtemp(prefix="yt-kids-test-"))

from core import licence


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def _page(html):
    licence._get = lambda url, timeout=40: html


CC0_PAGE = '<a href="https://creativecommons.org/publicdomain/zero/1.0/">CC0</a>'
NC_PAGE = '<a href="https://creativecommons.org/licenses/by-nc/4.0/">CC BY-NC</a>'
MIXED = CC0_PAGE + NC_PAGE


def test_a_cc0_page_is_cc0():
    print("test_a_cc0_page_is_cc0")
    _page(CC0_PAGE)
    lic, why = licence.freesound("https://freesound.org/people/x/sounds/1")
    check(lic == "cc0" and licence.usable(lic), "the CC0 deed and nothing else is CC0")


def test_what_openverse_got_wrong_is_refused():
    print("test_what_openverse_got_wrong_is_refused")
    _page(NC_PAGE)
    lic, why = licence.freesound("https://freesound.org/people/Mativve/sounds/514581")
    check(lic == "by-nc", f"a CC BY-NC page is read as by-nc ({lic})")
    check(not licence.usable(lic), "and is not usable on a monetised channel")


def test_a_page_with_a_second_licence_is_not_cc0():
    print("test_a_page_with_a_second_licence_is_not_cc0")
    _page(MIXED)
    lic, _ = licence.freesound("https://freesound.org/x")
    check(lic != "cc0", "CC0 next to another licence is not trusted as CC0")


def test_an_unreadable_page_is_a_refusal():
    print("test_an_unreadable_page_is_a_refusal")

    def boom(url, timeout=40):
        raise OSError("no route")
    licence._get = boom
    lic, _ = licence.freesound("https://freesound.org/x")
    check(lic == "unknown" and not licence.usable(lic), "unknown is never usable")
    _page("<html>no licence here</html>")
    check(licence.freesound("https://freesound.org/x")[0] == "unknown",
          "a page that names no licence is unknown, not assumed free")


def test_attribution_is_only_usable_when_asked_for():
    print("test_attribution_is_only_usable_when_asked_for")
    check(not licence.usable("by"), "CC BY is refused by default")
    check(licence.usable("by", allow_by=True), "and accepted only when the caller can carry it")
    check(licence.usable("pdm"), "public domain is always usable")


def test_a_host_with_no_verifier_is_unknown():
    print("test_a_host_with_no_verifier_is_unknown")
    lic, why = licence.verify({"page": "https://www.jamendo.com/track/1210823"})
    check(lic == "unknown", "Jamendo cannot be read, so it is refused rather than trusted")
    check("jamendo" in why, "and the reason names the host")


if __name__ == "__main__":
    real = licence._get
    try:
        test_a_cc0_page_is_cc0()
        test_what_openverse_got_wrong_is_refused()
        test_a_page_with_a_second_licence_is_not_cc0()
        test_an_unreadable_page_is_a_refusal()
        test_attribution_is_only_usable_when_asked_for()
        test_a_host_with_no_verifier_is_unknown()
    finally:
        licence._get = real
    print("ALL LICENCE TESTS PASSED")
