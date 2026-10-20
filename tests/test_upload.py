"""Offline tests for the upload stage. Run: python tests/test_upload.py

No network. The request body is built and inspected; nothing is sent. What matters most here
is the thing the law cares about - selfDeclaredMadeForKids - and the slot arithmetic that
keeps the channel on its schedule when GitHub starts a run hours late.
"""
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.logger
core.logger.LOG_DIR = Path(tempfile.mkdtemp(prefix="yt-kids-test-"))

from core import config, db
import pipeline.upload as up


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


CFG = {"timezone": "Europe/Kiev", "publish_time": "16:00", "publish_days_ahead": 3,
       "schedule_publish": True, "privacy_status": "private"}
VIDEO = {"seo_title": "6 Sea Animals for Kids | Learn Ocean Animals with Real Sounds",
         "description": "Learn 6 sea animals.", "tags": '["sea animals", "kids"]'}


def _fresh(tmp, name):
    db.DB_PATH = tmp / f"{name}.db"
    db.init_db()


def test_every_upload_is_declared_made_for_kids(tmp):
    print("test_every_upload_is_declared_made_for_kids")
    _fresh(tmp, "kids")
    body = up.build_body(VIDEO, CFG, datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc))
    check(body["status"]["selfDeclaredMadeForKids"] is True,
          "selfDeclaredMadeForKids is true on the request")
    check(body["status"]["containsSyntheticMedia"] is True,
          "and the synthetic-voice flag is set too")
    check(body["snippet"]["categoryId"] == "27", "in the Education category")
    for hostile in ({"made_for_kids": False}, {"youtube": {"made_for_kids": False,
                                                           "selfDeclaredMadeForKids": False}}):
        again = up.build_body(VIDEO, {**CFG, **hostile},
                              datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc))
        check(again["status"]["selfDeclaredMadeForKids"] is True,
              f"no config edit can turn it off ({list(hostile)[0]})")


def test_the_flag_is_checked_again_just_before_sending(tmp):
    print("test_the_flag_is_checked_again_just_before_sending")
    _fresh(tmp, "assert")
    body = up.build_body(VIDEO, CFG, datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc))
    up.assert_mandatory_flags(body)
    check(True, "a correct body passes")
    for bad in (False, None):
        broken = {**body, "status": {**body["status"], "selfDeclaredMadeForKids": bad}}
        try:
            up.assert_mandatory_flags(broken)
            check(False, f"{bad!r} should have been refused")
        except up.UploadError as e:
            check("COPPA" in str(e), f"{bad!r} is refused, and the message says why")


def test_a_scheduled_video_goes_up_private_for_16_00_kyiv(tmp):
    print("test_a_scheduled_video_goes_up_private_for_16_00_kyiv")
    _fresh(tmp, "slot")
    summer = up.publish_at(CFG, datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc))
    winter = up.publish_at(CFG, datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc))
    check(summer == "2026-10-15T13:00:00Z", f"16:00 Kyiv in summer is 13:00Z ({summer})")
    check(winter == "2026-01-18T14:00:00Z", f"and 14:00Z in winter ({winter})")
    body = up.build_body(VIDEO, {**CFG, "privacy_status": "public"},
                         datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc))
    check(body["status"]["privacyStatus"] == "private",
          "a scheduled video is forced private, which is what YouTube requires")


def test_the_slot_follows_the_queue_not_the_clock():
    print("test_the_slot_follows_the_queue_not_the_clock")
    taken = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)
    on_time = up.publish_at(CFG, datetime(2026, 10, 12, 1, 17, tzinfo=timezone.utc), taken)
    late = up.publish_at(CFG, datetime(2026, 10, 12, 7, 1, tzinfo=timezone.utc), taken)
    check(on_time == late == "2026-10-16T13:00:00Z",
          f"a run at the cron hour and one six hours late book the same slot ({on_time})")
    midnight = up.publish_at(CFG, datetime(2026, 10, 12, 22, 40, tzinfo=timezone.utc), taken)
    check(midnight == "2026-10-16T13:00:00Z", "and so does one that slips past local midnight")
    second = up.publish_at(CFG, datetime(2026, 10, 12, 7, 1, tzinfo=timezone.utc),
                           datetime.fromisoformat(on_time.replace("Z", "+00:00")))
    check(second == "2026-10-17T13:00:00Z", "two runs in one day take consecutive days")


def test_nothing_in_the_upload_code_depends_on_what_kids_videos_lose():
    print("test_nothing_in_the_upload_code_depends_on_what_kids_videos_lose")
    source = (ROOT / "pipeline" / "upload.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.strip().startswith("#"))
    body = code.split('"""', 2)[-1]                   # past the module docstring
    for forbidden in ("endScreen", "end_screen", "commentThreads", "allowedComments",
                      "pinned", "notifySubscribers", "playlistItems"):
        check(forbidden not in body, f"no reference to {forbidden}")


def test_what_youtube_stored_is_written_down_including_what_it_left_out():
    print("test_what_youtube_stored_is_written_down_including_what_it_left_out")
    from pipeline import upload
    said = upload.describe_stored({
        "snippet": {"channelId": "UC123", "channelTitle": "Moo Toot"},
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": True}})
    check("channel UC123 (Moo Toot)" in said, f"names the channel: {said[:60]}")
    check("selfDeclaredMadeForKids=True" in said, "the made-for-kids flag as stored")
    check("madeForKids=not echoed" in said,
          "and a field YouTube left out is written as not echoed, not skipped")
    check("channel not echoed" in upload.describe_stored({}), "an empty response does not crash")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        test_every_upload_is_declared_made_for_kids(tmp)
        test_the_flag_is_checked_again_just_before_sending(tmp)
        test_a_scheduled_video_goes_up_private_for_16_00_kyiv(tmp)
        test_the_slot_follows_the_queue_not_the_clock()
        test_nothing_in_the_upload_code_depends_on_what_kids_videos_lose()
    test_what_youtube_stored_is_written_down_including_what_it_left_out()
    print("ALL UPLOAD TESTS PASSED")
