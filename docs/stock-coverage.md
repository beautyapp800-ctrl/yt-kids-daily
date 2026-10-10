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

## Can the "is it really a whale" step be automated?

Measured on the same 59 frames, against the verdict in `data/human-verdict.json` which was
written down before any model was asked.

| policy | catches the 12 wrong frames | loses good frames (of 29) |
|---|---|---|
| vision-language model alone | **9** | **0** |
| classifier (resnet-50) alone | 8 | 5 |
| either model says yes | 8 | 0 |
| both must say yes | 9 | 5 |

So the describer decides and the classifier stands in only when the describer cannot be
reached. The classifier's failure is structural: it must return one of a thousand classes, so
it cannot say "this is a sunset, not an orange" - it says "rapeseed, 0.6" and sounds sure.

Of the three it still lets through, none is really the model being wrong about the subject:
the airplane clip is a wing filmed from inside the cabin, the bee clip is a beekeeper's frame
with bees on it, and the starfish clip does have a starfish in it, a few pixels across. All
three are bad framing, not the wrong thing, and framing is a separate measurement - subject
size in frame - not something a classifier has any business ruling on.

Two of the twelve are also arguable in the other direction: "chicken" returned a rooster,
which is a chicken, and the model was right to pass it. It was only wrong for us because the
same shot already serves the rooster card.

**The catalogue can therefore grow by itself.** New subjects are searched, every candidate
frame is put to the describer, and only those it confirms enter `assets/clips.json`. Nothing
is thrown away silently: a rejected clip is recorded with what the model said it was.
