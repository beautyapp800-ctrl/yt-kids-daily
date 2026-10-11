"""What a failure means, and what the owner has to do about it - if anything.

The factory runs unattended, so every way it can stop has to end in one of two places: it heals
itself on a later run, or an email names the one thing a person must do. "The run went red, go
and read the log" is neither.

This is yt-kids's own table, not a copy of yt-factory's. That project fails on a language
model rejecting a script; this one has no scripts and fails on different things - a catalogue
too thin to plan a video from, a clip that will not download, a stock site refusing the
runner's address, a card with nothing to show. The shape is the same: each failure becomes a
kind, a yes/no on whether waiting fixes it, and one sentence of instruction.

Patterns are matched against the stage name and the message together, most specific first.
Anything unrecognised is reported as unknown - explicitly, rather than looking like a handled
case.
"""
import re

# (kind, heals_itself, regex, action)
RULES = [
    ("youtube-auth", False,
     r"(token|credential|oauth|refresh).{0,60}(expired|revoked|invalid|not work|failed)|"
     r"invalid_grant|unauthorized_client|401.{0,40}youtube|youtube.{0,40}401",
     "Re-issue the YouTube token: run `python scripts/youtube_auth.py` on your own machine, "
     "signed in as the account that owns the KIDS channel, then paste the new token.json into "
     "the YOUTUBE_TOKEN_JSON secret of this repository. Nothing uploads until that is done."),

    ("made-for-kids", False,
     r"selfdeclaredmadeforkids|madeforkids|coppa",
     "YouTube did not store the made-for-kids declaration the way it was sent. That is a legal "
     "matter, not a cosmetic one: open the video in YouTube Studio today, Details > Audience, "
     "and set 'Yes, it's made for kids'."),

    ("youtube-upload-quota", True,
     r"uploadlimitexceeded|quotaexceeded|dailylimitexceeded|exceeded.{0,40}quota",
     "Nothing. YouTube's daily upload allowance is used up. The finished video stays on disk "
     "at 'ready' and the next run uploads it before starting anything new."),

    ("cloudflare-quota", True,
     r"(cloudflare|neuron|allocation).{0,80}(quota|limit|exceed|10000|10,000|used up)|"
     r"quotaexhausted|cloudflare http 429",
     "Nothing. The daily Cloudflare allowance is spent, and it is only touched when a card has "
     "no footage and has to be drawn. The next run draws what is still missing; clips already "
     "downloaded are kept in the run cache."),

    ("catalogue-too-thin", False,
     r"only \d+ cards (could be planned|had a checked fact)",
     "The catalogues cannot supply enough cards for a video. Run `scripts/build_catalogue.py`, "
     "`scripts/build_facts.py` and `scripts/build_sounds.py` (or let the weekly grow job do it) "
     "- this will not clear by itself, because nothing is adding subjects."),

    ("secret-missing", False,
     r"secrets not set|not set in \.env|api[_ ]?key.{0,30}(missing|not set)",
     "A repository secret is missing or empty. Settings > Secrets and variables > Actions, "
     "and set the one the message names."),

    ("tts-blocked", False,
     r"edge-tts.{0,80}(403|refus|blocked)|403.{0,40}edge-tts",
     "Microsoft is refusing the runner's address for free speech synthesis. This does not "
     "clear by itself; another voice from the same service, or running that stage elsewhere, "
     "is the way round."),

    ("stock-site-refused", True,
     r"(pixabay|cdn\.pixabay).{0,80}(403|429|refus|forbidden)|403.{0,40}pixabay",
     "Nothing for now - Pixabay's CDN refused the runner. Cards whose clip could not be fetched "
     "are drawn instead, so the video still goes out; if every card is drawn day after day, the "
     "runner's address is blocked and the clips need hosting somewhere else."),

    ("rate-limited", True,
     r"429|rate.?limit|too many requests",
     "Nothing for now - the service is throttling and the next run tries again."),

    ("service-down", True,
     r"\b5\d\d\b|timed? ?out|timeout|connection (reset|refused|aborted)|"
     r"temporarily unavailable|network error|urlerror|bad gateway|getaddrinfo",
     "Nothing. A service the pipeline uses was unreachable; the next run resumes from the "
     "stage that failed and does not repeat what is already done."),

    ("no-picture", False,
     r"no picture at all|has neither a clip nor a picture",
     "A card ended up with neither footage nor a drawing, which means both the stock site and "
     "the picture generator failed for it. If it repeats, check the Cloudflare token and the "
     "clip catalogue for that subject."),

    ("render", False,
     r"ffmpeg|ffprobe|no such file or directory.{0,40}\.(mp4|mp3|wav)|moov atom|renderers?",
     "The render failed on the video tool itself rather than on anything external. This is the "
     "one class here that is likely a defect in the code, not a service having a bad day, and "
     "it needs a look at the run log."),
]

UNKNOWN_ACTION = ("This failure is not one the factory knows how to classify. Read the run "
                  "log at the link below; if it turns out to be a recurring kind, it belongs "
                  "in core/failures.py so the next email can say what to do.")


def classify(stage, message):
    """(kind, heals_itself, action) for a recorded failure."""
    text = f"{stage or ''}: {message or ''}".lower()
    for kind, heals, pattern, action in RULES:
        if re.search(pattern, text):
            return kind, heals, action
    return "unknown", False, UNKNOWN_ACTION


def action_for(stage, message):
    """Just the sentence of instruction, for putting straight into an email."""
    return classify(stage, message)[2]
