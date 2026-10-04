# Kim layout audit (pilot-11, 2026-10-04)

20 paired flights, stopped early for futility. This run does **not** report an
attack effect. It reports which layout families Kim can fly at all, which is why
it is kept.

## What was flown

`agent_campaign.py --policy random --planner kim --budget 80 --seed 42`, with 24
qualified layouts drawn from `easy`, `medium`, `hard` (seeds 0-7). Every round
flies the same layout twice, once clean and once perturbed, so layout difficulty
cancels within the pair. Worker image and both trees were constant across all
flights.

Stopped at 20 pairs. The stopping rule was fixed at 6 pairs, before the numbers
below existed: *if clean pass rate is under 0.25 at 20 pairs, re-weight toward
easier layouts.* It keys on the clean arm alone, which carries no information
about the attack effect, so acting on it cannot bias the contrast.

## Result

```
                 n     clean          attack         b   d   McNemar p
ALL             20   3/20 [.05,.36]  4/20 [.08,.42]  2   3   1.0000
hard             8   0/8  [.00,.32]  0/8  [.00,.32]  0   0   1.0000
medium           4   0/4  [.00,.49]  1/4  [.05,.70]  0   1   1.0000
easy             8   3/8  [.14,.69]  3/8  [.14,.69]  2   2   1.0000
```

`b` = clean passed, attack failed (the attack working). `d` = the reverse.
Intervals are Wilson score.

**Kim completed zero of 8 `hard` pairs and zero of 4 `medium` pairs, clean or
attacked.** Those 12 pairs are fail/fail concordant and contribute nothing to
McNemar, which uses only discordant pairs. 60% of the budget bought no
information. The 5 discordant pairs split 2/3 against the attack, which at this
n is noise.

Note the attack arm passed *more* often than clean overall (4 vs 3). That is not
evidence of a protective patch. It is what a null looks like at n=20 when the
baseline is near the floor.

## Why the baseline was that low

A selector bug, not a property of Kim. `layouts.json` orders the families by
objects per variant:

```
furnished_a   6
furnished_b   7
easy         11
medium       15
hard         19
```

`easy` is the third-hardest of five, not the easiest. The qualified-layout list
covered the three hardest families and omitted the two simplest ones entirely.

The omission was not avoidable by passing different flags. `agent_schema.py`
built `LAYOUTS` from `conditions.DIFFICULTY_COUNTS`, which holds only
`easy`/`medium`/`hard`, while `conditions.validate()` has always accepted
`furnished_a` and `furnished_b`. The agent's action space and the simulator's
accepted scenes had drifted apart, so no agent policy could select either simple
family, and `parse_qualified_layouts` carried a second hardcoded copy of the same
narrow list. Both are fixed in the commit that adds this directory.

## What follows

`kim_flyable` re-runs the paired design over `furnished_a`, `furnished_b` and
`easy` (24 layouts, seed 43, budget 64). Restricting to these three is not scene
hand-picking: the policy still chooses freely, and the families removed are ones
with a provably dead clean baseline, which can never discriminate an attack.

Do not pool these 20 pairs with `kim_flyable`. Different layout families,
different seed, and the action-space fix means the trees differ.
