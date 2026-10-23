# yt-kids

Learning videos for two- to six-year-olds, in English, made and published automatically: one
video a day, 20-30 cards, each a real thing shown, named, heard, and given one short fact.

Real footage first, because a real whale swimming beats any drawing of one for a two-year-old;
our own pictures only where there is none. A separate project from yt-factory (Stoicism): it
borrows approaches and some ported code, but has its own database, its own Cloudflare account
and its own repository.

## Made for kids (COPPA)

This channel is for children, so every upload sets `status.selfDeclaredMadeForKids = true` and
the channel is set the same way. That is a legal requirement, not a preference, which is why it
is a constant in `pipeline/upload.py` rather than a config value: no edit to `config.json`
can switch it off, it is asserted on the request immediately before sending, the value YouTube
stores is compared with the one sent, and `config.py` refuses to load a config that says
otherwise.

What follows from it, none of which any code here relies on: comments are off, end screens and
cards do not work, subscribers are not notified of new videos, personalised ads are off.

## How a video is made

```
plan -> media -> narrate -> render -> seo -> thumbnail -> upload
```

**The daily run asks no model anything.** The plan reads three catalogues, each checked once
when an entry was added, and `tests/test_daily_cost.py` holds that line. The only thing a run
can spend from the free Cloudflare allowance (10,000 neurons a day) is drawing a card that has
no footage. That is the reason this can run daily on the free tier at all: an earlier version
judged sound candidates live, about a hundred model calls a day for answers that never change,
and exhausted the allowance mid-run.

| catalogue | file | checked by | checked how |
|---|---|---|---|
| clips | `assets/clips.json` | a vision model | asked what the subject of the frame is, never whether it is a whale |
| facts | `assets/facts.json` | a judge | asked to find the error, never whether the fact is true |
| sounds | `assets/sounds.json` | the hosting page, then a judge | licence read at the source; then asked what the recording actually is |

Measured, not assumed (`docs/stock-coverage.md`, `docs/fact-accuracy.md`):

- clips: the vision model rejects 9 of the 12 frames that show the wrong thing and throws away
  none of the 29 good ones. Stock search alone returns a surfer for "shark" and a fairground
  ride for "octopus";
- facts: 3 of the first 40 the model wrote were false and all passed the structural rules. One
  judge (the 70b) catches 17 of 17 false facts and refuses 4 of 37 true ones;
- sounds: three of the first five were not the animal - a push-button torch made by a company
  called Dolphin, a MIDI of "Baby Shark", a person reciting "O is for octopus".

## Licences

The repository is public and the channel is monetised, so anything used has to be CC0 or public
domain. **The licence is read from the page that hosts the file, not from Openverse**
(`core/licence.py`): Openverse reported "Happy FROG" as CC0 and its Freesound page says CC
BY-NC 4.0. Where the source cannot be read the answer is unknown, and unknown is refused.

Music: two CC0 tracks in `assets/music/`, each confirmed at its source (`licences.json`). Their
level is measured, not chosen - the bed is put 12 dB under the narration and the gap is read
back off the finished mix.

## The video

Six and a half minutes, every video, in two halves.

**Learn.** The video opens on a board of the fifteen subjects. Each card is a cell growing to
fill the screen, the real footage, the name, the real sound where it has one, one short fact,
and back to the board with a green tick. Pace measured against a competitor with 4.5 million
views: about ten seconds a card.

**Guess who?** A full-screen card and a short CC0 sting, then the same fifteen in a shuffled
order (`pipeline/game.py`). Each turn: a riddle, the real sound, a question, a countdown 3-2-1
with a tick, the reveal with a whoosh or a pop and confetti, "Yes! It's a lion!" with the name
on screen, the sound again. The riddle is a frozen frame of a second clip of the subject, cut
to a detail of it - stripes, a face, a fan of feathers; where the detail would be a piece of
background (the catalogue measured the subject as small) or there is nothing in it to see, the
whole frame heavily blurred. At the reveal the camera pulls back over that frozen frame with
the same eased affine flight the board uses, and the clip starts playing from that frame.

The length is held by the game: everything before it is built and measured, the fifteen turns
share what is left to reach 390 seconds, and each turn's closing hold moves by the same amount.
Measured on the first build: learning 190.0 s, the card 5.8 s, fifteen turns 182.6 s, the
goodbye 11.5 s - 390.0 s, picture and sound within 0.02 s of each other.

Levels are measured on the mixed turns, not assumed: the voice is the same in both halves
(-18.8 and -19.4 dBFS), ticks sit 13.5-15.2 dB under it, the whoosh and pop 6-12 dB under, the
sting 4 dB under. The effects are CC0, each licence read on its Freesound page
(`assets/sfx/licences.json`, found by `scripts/find_sfx.py`).

## One video, one theme

A video is one theme - farm animals, or birds, or vehicles - and never a mixture. The first
three videos were planned from a whole family of themes, and all three came out called "30
Animals for Kids", sharing twenty subjects of thirty and showing the same lions on the same
covers. From a viewer's seat that is one video three times.

One theme per video also spaces the subjects out with no further rule: with seven themes in
rotation a theme returns every seventh video, so nothing inside it can come back sooner. The
arithmetic the old way could never satisfy - thirty cards and no repeat within five videos
needs 150 distinct subjects, and the animals family has 52.

A video is therefore as long as its theme allows: `cards_per_video` is a ceiling, the theme's
own size is the number, and `min_theme_cards` is the floor below which a theme is skipped.
Titles rotate through six shapes and are checked against the last ten in the database; cover
cells avoid the subjects on the last ten covers.

## Staying supplied

`scripts/grow.py` (the `grow` workflow) fills the themes that cannot yet fill a video, neediest
first. Candidates come from `assets/subject-pool.json`, written by hand rather than asked of a
model: the model proposed "horse cart" as a farm animal, and it proposed species no verifier
can confirm - sparrow, finch, toucan and hummingbird all came back from the describer as
"bird", goose as "duck", pony as "horse". Those refusals are correct, so the pool is written at
the level a small child names things. Where a subject's own name finds the wrong thing in a
stock library - "turkey" returned Istanbul twelve frames running - `search_terms` in the same
file says what to type instead.

## Automation

`daily` (two crons a day, because GitHub starts scheduled jobs hours late and may drop one),
`heartbeat` (did a video join the queue today?), `publish-check` (did it really go public?),
`grow`. Publication is 16:00 Kyiv, morning in the US, booked from the end of the queue rather
than from the clock so a late runner cannot skip a day.

Setup, including exactly what to click: `docs/setup.md`.

## Known limits

- **The cover is the board, not a cut-out.** The video's own board cut down to eight cells.
  Which eight is decided by what the catalogue measured once per clip when it was added
  (`scripts/inspect_frames.py`, docs/cover.md): an object detector for how much of the frame
  the subject fills and for people, the describer for people and built things. Each signal
  alone was checked by eye on all 216 frames and found wrong in a known way - the detector
  counts penguins as people and gives a strawberry no box at all, the describer puts a building
  beside a chicken in an empty field - so people need both models to agree, "no box" is
  unknown rather than small, and built things lower a frame's chances without ruling it out.
- **Sounds are judged by words, not by ears.** There is no free classifier that listens to four
  seconds and says "dolphin"; the judge reads the title and tags. It catches a torch, a MIDI and
  an alphabet recording, and would miss a recording of the sea filed as "shark swimming".
- **Footage is only as framed as the stock library.** The dolphin is filmed in an aquarium with
  visitors' silhouettes. The model correctly confirms it is a dolphin and does not judge that
  there are also people in the shot.
- **Cloudflare's reset time is not midnight UTC.** The allowance was spent at about 17:00 UTC on
  10 October and still spent at 06:14 UTC on the 11th, and open by 07:56.
