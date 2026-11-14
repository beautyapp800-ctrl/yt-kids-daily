"""YouTube credentials, shared by scripts/youtube_auth.py (which creates them) and
pipeline/upload.py (which uses them).

Same code as yt-factory, and a different token: this channel has its own Google
account and its own YOUTUBE_TOKEN_JSON secret. Nothing is shared between the two.

Two scopes. youtube.upload covers videos.insert and thumbnails.set. youtube.readonly is
there for one question only: which channel is this token for? On 14 November 2026 the project
moved from Moo Toot to another channel, and a Google account can own several channels - so
before anything is uploaded the token is asked for its channel (channels.list mine=true) and
compared with config.youtube_channel_id. A token that cannot answer (the old upload-only one)
or answers with another channel uploads nothing. The broader `youtube` scope, which would let
the token edit and delete videos, is still not asked for.

The token is the long-lived secret: a refresh token that can upload to the channel. It
lives in secrets/token.json, which .gitignore keeps out of the (public) repository. For CI
the same JSON goes in a GitHub Secret and is passed as the YOUTUBE_TOKEN_JSON environment
variable, which is read first.
"""
import json
from pathlib import Path

import os

ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_PATH = ROOT / "credentials.json"
TOKEN_PATH = ROOT / "secrets" / "token.json"
TOKEN_ENV = "YOUTUBE_TOKEN_JSON"

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
SCOPES = [UPLOAD_SCOPE, READONLY_SCOPE]

REAUTH_HINT = ("run  python scripts/youtube_auth.py  again to sign in and create a fresh "
               "token")


class AuthError(Exception):
    pass


def load_credentials(token_path=TOKEN_PATH):
    """The saved credentials, refreshed if the access token has expired.

    The refresh token itself does not expire while the Google Cloud project's consent
    screen is "In production" (and the token is used at least once every six months). On a
    project left in "Testing" it dies after seven days, which shows up here as a refresh
    failure, and is the first thing to check.
    """
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    from_env = os.environ.get(TOKEN_ENV)
    token_path = Path(token_path)
    if from_env:
        info = json.loads(from_env)
    elif token_path.exists():
        info = json.loads(token_path.read_text(encoding="utf-8"))
    else:
        raise AuthError(f"no YouTube token at {token_path} and no {TOKEN_ENV} set; "
                        f"{REAUTH_HINT}")

    # The token's own scopes, not SCOPES: an older token asked to refresh with a scope it
    # was never granted fails with a confusing error, and verify_channel() gives a clear one.
    creds = Credentials.from_authorized_user_info(info, info.get("scopes") or SCOPES)
    if not creds.refresh_token:
        raise AuthError(f"the saved token has no refresh token; {REAUTH_HINT}")
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise AuthError(
                f"Google refused to refresh the YouTube token ({e}). The usual cause is a "
                "consent screen still in 'Testing', which expires tokens after 7 days; "
                f"otherwise it was revoked. Fix that, then {REAUTH_HINT}.") from e
        if not from_env:
            token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def build_service(creds):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def channel_of(service):
    """(channel id, title, handle) of the channel this token uploads to.

    channels.list with mine=true costs 1 quota unit. A Google account with several channels
    answers with the one chosen at sign-in.
    """
    response = service.channels().list(part="snippet", mine=True).execute()
    items = response.get("items") or []
    if not items:
        raise AuthError("the token belongs to a Google account with no YouTube channel")
    if len(items) > 1:
        raise AuthError(f"the token answers for {len(items)} channels; sign in again and "
                        f"choose one")
    item = items[0]
    snippet = item.get("snippet") or {}
    return item["id"], snippet.get("title", ""), snippet.get("customUrl", "")


def verify_channel(service, expected_id, creds=None):
    """Raise AuthError unless the token is for `expected_id`. Returns (id, title, handle).

    Called before every upload: the old Moo Toot token is still a valid token, and the one
    thing worse than no video is a video on the wrong channel.
    """
    if not expected_id:
        raise AuthError("config.youtube_channel_id is not set, so it cannot be checked which "
                        "channel the token uploads to; nothing is uploaded")
    granted = set(getattr(creds, "scopes", None) or []) if creds is not None else None
    if granted is not None and READONLY_SCOPE not in granted:
        raise AuthError("this token cannot say which channel it is for (it has no "
                        "youtube.readonly scope - it is the old upload-only token); "
                        f"{REAUTH_HINT}")
    channel_id, title, handle = channel_of(service)
    if channel_id != expected_id:
        raise AuthError(f"the token is for channel {title!r} {handle} ({channel_id}), not "
                        f"{expected_id}; nothing is uploaded. Sign in again and choose the "
                        f"right channel: {REAUTH_HINT}")
    return channel_id, title, handle


def checked_service(cfg):
    """A YouTube service whose token has been checked against config.youtube_channel_id."""
    creds = load_credentials()
    service = build_service(creds)
    verify_channel(service, (cfg or {}).get("youtube_channel_id"), creds)
    return service
