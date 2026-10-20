# What the cover knows about a frame

Measured once per clip, when it joins the catalogue, and stored with it in `assets/clips.json`.
The daily run reads it and asks no model.

| field | from | means |
|---|---|---|
| `subject_area` | `@cf/facebook/detr-resnet-50` | largest non-person box, share of the frame; `null` if nothing recognised |
| `people_detected` | the detector | persons at score >= 0.8, outside the subject's own box |
| `people` | detector AND describer | `people_detected`, but only if the describer also names a person |
| `structures` | `@cf/llava-hf/llava-1.5-7b-hf` | built things it names when asked to list everything it sees |

## Checked by eye, all 216 frames

**Area.** The catalogue's older `prominence` is the classifier's confidence in its label, not
a share of the frame: it read 1.00 for 23 of 30 frames. The detector's boxes are a real
measurement, with two limits found on the contact sheets:

- it knows COCO's 80 classes. 30 frames got no box, among them a strawberry filling the screen,
  jellyfish, a whale, a wolf, a monkey. So no box is stored as `null`, unknown, not 0%;
- its boxes under-measure. A lion filling a quarter of the frame read 4.1%, an elephant 3.7%.

Below 2% with a box, every frame on the sheet really was a speck: a cow across a valley, a
tractor from the air, zebras on the horizon, a helicopter in the sky. 49 clips. That is the
line (`thumbnail.SMALL_SUBJECT`); above it, area is a small nudge in the ranking.

**People.** The detector flagged 15 frames. 9 were real - the orca show, the aquarium glass,
hands cutting a carrot and a watermelon, people beside helicopters. 6 were not: 12 "people" in
a penguin colony, 3 in another, a spider, a starfish, a crab, a grey frame. Requiring the
describer to name a person as well removed exactly those 6 and kept the 9. On a vehicle a
person is the driver or the rider and does not count against the frame.

**Built things.** 17 animal or food frames. About half real (aquarium, show pool, shed, wall),
the rest invented - "building" beside a chicken in an empty field. Too noisy to veto with, so it
costs a frame 0.3 in the ranking instead.

Result: 54 of 216 clips are kept off covers. Two subjects have no frame fit for one (apple,
boat); they can still be on a cover if the board cannot be filled otherwise.
