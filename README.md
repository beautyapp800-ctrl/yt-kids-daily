# yt-kids

Learning videos for two- to six-year-olds, in English, made and published automatically.
One video a day: 20-30 cards, each a real thing shown, named, and given one short fact.

A card holds the screen for 12-18 seconds. Real footage first, our own pictures where there
is none, because a real whale swimming beats any drawing of one for a two-year-old.

This is a separate project from yt-factory (Stoicism). It shares approaches and some code,
but not a database, not a Cloudflare account, and not a repository.

## COPPA

This channel is made for children, so every upload declares
`status.selfDeclaredMadeForKids = true` and the channel is set the same way. That is a legal
requirement, not a preference. It has consequences that the code must not fight:

- comments are off,
- end screens and cards do not work,
- subscribers are not notified of new videos,
- personalised ads are off, so revenue per view is lower.

Nothing in this repository may be written to depend on any of those.

## Where the footage comes from

See `docs/stock-coverage.md` for the measurement that decided the proportion between filmed
and drawn cards, and `scripts/stock_probe.py` for the code that produced it.
