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

The card is a move on a board (`pipeline/grid.py`). The video opens on every subject at once;
each card is its cell lighting up, growing to fill the screen, becoming the footage, and coming
back with a green tick. A child who cannot count still sees the board fill up. All stills and
ffmpeg, and measured: the board render is faster than the xfade joins it replaced, because the
zooms are the transitions and nothing long is re-encoded twice.

Pace was measured against a competitor with 4.5 million views: ten seconds a card, metronomic,
no talk between cards. A question is kept for every fourth card, as a change of pace.

The voice is Microsoft's `en-US-JennyNeural`, chosen by ear from three samples. Two rates in
`config.json` - `rate_name` and `rate_speech` - so the name and everything else can be tuned
separately.

## Staying supplied

Sixty subjects is two videos. `scripts/grow.py` (the `grow` workflow) counts how many videos'
worth of fresh subjects are left; below three it asks for new subjects in the thinnest themes
and runs the same three builders on them. The daily self-check warns when the supply is low.

## Automation

`daily` (two crons a day, because GitHub starts scheduled jobs hours late and may drop one),
`heartbeat` (did a video join the queue today?), `publish-check` (did it really go public?),
`grow`. Publication is 16:00 Kyiv, morning in the US, booked from the end of the queue rather
than from the clock so a late runner cannot skip a day.

Setup, including exactly what to click: `docs/setup.md`.

## Known limits

- **The cover is the board, not a cut-out.** Lifting an animal out of stock footage was
  measured and does not work (a shark's eye, a whale's tail with part of a platform). The cover
  is the video's own board cut down to eight cells, chosen for colour, for how far the middle
  of the frame stands out from its edge, and for being an animal a two-year-old knows. Nothing
  here can see how big the animal is in the frame or whether there are people in it, so a
  show-pool whale or an aquarium dolphin can still be picked; `thumbnail.TINY` pushes down the
  creatures that are a speck in any frame. The names under the cells are drawn only when they
  measure 11 px at 210x118, which with eight cells they do not, so they are off.
- **Sounds are judged by words, not by ears.** There is no free classifier that listens to four
  seconds and says "dolphin"; the judge reads the title and tags. It catches a torch, a MIDI and
  an alphabet recording, and would miss a recording of the sea filed as "shark swimming".
- **Footage is only as framed as the stock library.** The dolphin is filmed in an aquarium with
  visitors' silhouettes. The model correctly confirms it is a dolphin and does not judge that
  there are also people in the shot.
- **Cloudflare's reset time is not midnight UTC.** The allowance was spent at about 17:00 UTC on
  10 October and still spent at 06:14 UTC on the 11th, and open by 07:56.
