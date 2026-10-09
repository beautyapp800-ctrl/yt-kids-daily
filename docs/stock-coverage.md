# How much can be filmed rather than drawn

Measured over the 60 subjects in `assets/subjects.json` with `scripts/stock_probe.py`.

## The numbers

| source | key | subjects with a hit | of those, actually showing the thing |
|---|---|---|---|
| Pixabay | free, instant | 59 of 60 (98%) | about 29 (49%) strong, 17 weak, 12 wrong |
| Wikimedia Commons | none | 30 of 60 (50%) | 1 or 2 of the 6 sampled |
| Pexels | suspended | - | - |
| Openverse | none | no video endpoint at all (HTTP 404) | - |

A hit counts only if the licence allows commercial use, the clip is at least 8 seconds and at
least 1280 wide, Pixabay's own `isAiGenerated` is false (the premise of this channel is a real
whale, and a generated clip is a drawing with extra steps), `isGRated` is true and
`isLowQuality` is false.

## Why the first number is not the real one

Search matches words, not pictures. Commons returned satellite footage of Typhoon Dolphin for
"dolphin" and an empty swimming pool for "whale". Pixabay is far better but fails the same
way: "orange" returned a sunset and then autumn trees, "carrot" a carrot flower, "school bus"
a school of fish, "train" a bridge at sunset, "octopus" a fairground ride of that name.

Matching the head noun against Pixabay's tags - "bus", not "school" - removes the grossest of
these. It is not enough: it changed four clips, improved two, and made "cow" worse (an aerial
of a field with cows as specks). A clip tagged "train" that shows no train cannot be caught by
reading tags, because the tag is not wrong, the framing is.

## What follows for the design

Stock search cannot be trusted at run time. The clips are therefore **curated once and stored**:
`assets/clips.json` holds, per subject, the Pixabay ids that were looked at and judged to show
the thing large, bright and unmistakably - with the licence recorded, since the repository is
public. A daily run picks from that catalogue and never searches live.

Subjects with no good clip are drawn instead. On the first pass that is roughly one in five,
and it falls as the catalogue is filled in, because most subjects have a good clip somewhere
in the first dozen results - the first result just is not it.
