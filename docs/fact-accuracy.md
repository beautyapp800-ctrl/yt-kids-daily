# Are the facts true?

A false fact costs more here than any bad frame. "The banana is yellow like a spoon" is caught
by looking at the shape of the sentence; "a seahorse swims upside down" is the right length,
names the thing, uses no measurements, and is false.

## The measurement

54 statements: 40 the model wrote by itself for the subject list, read and judged by eye and
recorded in `data/fact-verdict.json` before any checker was run, plus 14 planted false ones
written to pass every structural rule.

**Three of the 40 it wrote were false** — 7.5%, which is the error rate this is meant to stop:

| fact | what is wrong |
|---|---|
| A seahorse swims upside down. | they swim upright |
| A ladybug has red spots. | the spots are black, the wing cases red |
| A sea turtle swims slow. | fast in water; slow is their reputation on land |

| judge | catches false (of 17) | loses true (of 37) |
|---|---|---|
| **llama-3.3-70b alone** | **17 (100%)** | **4 (11%)** |
| llama-3.1-8b alone | 15 (88%) | 15 (41%) |
| either one rejects | 17 (100%) | 15 (41%) |
| both must reject | 15 (88%) | 4 (11%) |

So one judge, the 70b. Asking the 8b as well inherited its 41% loss and caught nothing extra.

The four true facts the 70b refuses are "a zebra has black stripes" (it has both), "a jellyfish
stings us" (not all do), "an owl sees in the dark" (not complete darkness) and "a parrot talks
like us" (it mimics). A careful editor would have queried all four. Losing them costs nothing,
because a refused fact is simply rewritten - which is the whole reason the check is set to
catch rather than to be fair.

## What it is not

The judge is the same model family that wrote the fact. This is not an independent source and
should not be described as one: it catches what a careful editor catches, not what an
encyclopaedia would. It is asked to find the error rather than to confirm the statement,
because a model asked "is this true?" agrees.

Facts are therefore checked **once, when they enter `assets/facts.json`**, and the daily run
takes a checked fact rather than writing a new one. Anything the judge refuses is kept in the
file with the reason, so the refusals can be read and the judge itself argued with later.
