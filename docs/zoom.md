# The flight between the board and a cell

The grow from a cell to the full screen was a `zoompan` over the board image. It juddered and
drifted. This is what was measured, what the cause turned out to be, and what replaced it.

## The measurement

A board was built that is black except for a white block inside one cell. The block's area
gives the apparent scale and its centroid the apparent position, both sub-pixel and without
any edge-finding. The flight was then rendered and every frame measured.

Judder is a velocity that changes direction from one frame to the next, so that is the number:

| | zoompan | affine, now |
|---|---|---|
| frames where the motion reversed | **12 of 15** | 1 of 15 |
| worst sideways jump in one frame | 8.9 px | - |
| drift of a centred block over the flight | 15.3 px | - |
| zoom rate, frame to frame | 0.319-0.345 when it should be constant | follows the eased curve |

The scale itself was nearly right - never more than 0.4% off the curve the formula asked for.
The position was the fault: `zoompan` holds the window's `x` and `y` in whole pixels, so as the
zoom grows the fraction it should have moved by is rounded away, and the picture is shoved a
pixel or two sideways, alternating direction. That is the judder, and the rounding always falls
the same way, which is the drift.

## What replaced it

Each frame is one affine resample of the board: crop, scale and tilt together, in floating
point, drawn with PIL and piped to ffmpeg as raw frames. Nothing is rounded and nothing is
resampled twice.

- **The window's width is geometric**, because the eye reads zoom as a ratio. Growing seven
  times over by equal steps of width crawls at the start and lunges at the end.
- **The centre is derived from the width, not interpolated beside it.** Interpolating both
  independently was tried and measured: shrinking the window about the board's centre
  magnifies the distance to an off-centre cell faster than the centre can travel, so the cell
  slid 107 px AWAY from the middle before swinging back. Now the cell's distance from the
  middle of the screen is what is interpolated, straight down to nothing.
- **The window is held inside the board.** The path above asks to look up to 43 px past the
  edge for a cell in a corner, so there the window slides along the edge instead - which is
  what panning across a picture does when you reach the side of it.
- **Cubic ease-in-out.** The first and last frames move 2.9 and 0.5 px against 258 px at the
  quickest moment.
- **A tilt of up to 3.5 degrees**, zero at both ends so neither join is crooked, peaking at
  about three quarters of the way rather than halfway: halfway the window is still most of the
  board and a corner cell would have no room for it. Every cell gets at least 2.5 degrees.

## What it costs

Drawing a frame is 134 ms, and the resample releases the interpreter lock, so the frames are
drawn on six threads: 2.41 s on one thread against 0.53 s on six. Bilinear would also have been
2.4x faster, but the last frames of a flight are a seven-fold enlargement of one cell, which is
the one place in this video that cannot afford a softer resample.

Per flight: 0.80 s against zoompan's 0.28 s to grow, 0.66 s against 0.25 s to shrink. Over
thirty cards, **43.8 s against 15.9 s - 28 seconds added to a run of about twelve minutes**.
