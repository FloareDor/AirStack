# pilot-9 factor cells: read this before quoting any number

These five cells measure one attack factor at a time on scene `easy:2`. They
were run to break a confound in the campaign data, where the ranker raises
delay and patch size in the same step so neither can be attributed.

## The cells are sound. The comparison I first drew from them was not.

Every cell here ran in workspace `ws2-pilot-9` on worker image `11b5fdfb`
with a clean AirStack tree. The clean baseline of 75/100 that these were first
compared against was flown in `ws2-pilot-8` on worker image `1cc81938`.
A different workspace rebuilds the worker image and gets a different digest
even at an identical git HEAD, so that comparison crosses builds and its
p-value is not usable.

There is no clean cell in pilot-9, so the two images cannot be checked against
each other. That is the gap to close next.

## Within-build numbers, which are the usable ones

All four flown in pilot-9 on the same image:

| condition                  | pass        |
|----------------------------|-------------|
| patch timed alone          | 25/39 0.641 |
| delay 0.25 alone           | 15/25 0.600 |
| ranker's modal config      | 14/25 0.560 |
| patch continuous alone     | 17/40 0.425 |

| contrast                            | p      |
|-------------------------------------|--------|
| continuous vs all non-continuous    | 0.059  |
| continuous vs timed alone           | 0.072  |
| continuous vs delay alone           | 0.21   |
| continuous vs ranker's modal        | 0.32   |

Nothing clears 0.05. The direction is consistent, continuous patch is the worst
condition in every contrast, but this is a suggestive pattern and not a result.

## A third build, in the campaign data

The pilot-8 campaigns (`cmp_random_*`, `cmp_search_*`, `cmp_agent_*`) ran with
uncommitted AirStack edits, `AirStack.diff_sha256 = a604f207...`, while the
pilot-8 repeat cells ran clean. So campaign pass rates are a third build state
and are not comparable to either set. This is why the ranker's 0.15 attacked
pass rate does not reproduce as 0.56 when its own modal configuration is flown
directly: different code, not noise.

`diff_sha256 = e3b0c442...` is sha256 of empty input, meaning a clean tree.

## What to do instead

Run `repeat_check.py --clean` so every attack cell is paired with a clean cell
in the same workspace, and budget the GPU time for it. Before quoting a
p-value, diff `provenance.json` across both arms; if `worker_image` or either
`diff_sha256` differs, the comparison is not usable.
