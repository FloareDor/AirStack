# Random vs search vs agent on MonoNav

Date: 2026-10-03
Workspace: OSMO `ws2-pilot-8`, one session, one GPU
Planner: MonoNav, layout `easy:2`, seed 42, no noise
Protocol: `--clean-failure-policy record` (see below), `--clean-validation-runs 0`

## 0. Summary

- **Search is the only method that found anything.** Attacked flights passed
  3/20 against its own clean controls at 16/20 in the same campaign,
  Fisher p = 0.00009. Search also beats the agent on attacked pass rate
  (p = 0.030) and the agent with the objective stated (p = 0.035).
- **Random and the agent are both indistinguishable from flying with no attack**
  (p = 1.00 and p = 0.63 against their own clean controls).
- The agent lost for a identifiable reason: it held sensor delay at the minimum
  for **10 of 10 rounds** and spent the campaign varying the patch, which is the
  factor measured to have no effect.
- Adding **one sentence** stating the objective changed that behaviour
  completely: delay escalation returned immediately. It did **not** improve what
  the agent found. At 10 pairs the attacked pass rate looked much better
  (0.60 -> 0.30); extending to 18 pairs it regressed to 0.50, p = 0.71 against
  the plain agent. The early gain was noise.

## 1. The guard had to be changed before any of this could run

At the measured clean pass rate of 0.60, a campaign that halts the first time a
clean control fails completes a 4-round budget only 13% of the time
(`0.60^4`). Every pilot campaign truncated for this reason, and the pilot's
agent arm got 2 attacked flights where random got 4, so it was never a
comparison of methods.

`--clean-failure-policy record` keeps flying and lets `verdict()` mark the pair
`invalid_clean_baseline`, so a failed control can never be counted as a
candidate. Default remains `halt`.

In this run the clean control failed in **round 2 of random, round 2 of search
and round 3 of the agent**. Under `halt` the three campaigns would have ended
with 1, 1 and 2 usable rounds.

## 2. Results

| method | rounds | candidates | expected from baseline | attacked pass | clean pass | vs own clean |
|---|---|---|---|---|---|---|
| random | 10 | 3 | 2.6 | 4/10 = 0.40 | 5/10 = 0.50 | p = 1.00 |
| **search** | 20 | **13** | 5.3 | **3/20 = 0.15** | 16/20 = 0.80 | **p = 0.00009** |
| agent | 10 | 3 | 2.6 | 6/10 = 0.60 | 8/10 = 0.80 | p = 0.63 |
| agent + objective | 18 | 7 | 4.8 | 9/18 = 0.50 | 13/18 = 0.72 | p = 0.31 |

"Expected from baseline" is what the measured clean failure rate (1 - 0.735)
produces across 10 attacked flights with no attack effect at all. Random and the
agent sit on top of it. Search is well above it.

Pairwise on attacked pass rate, search against each other arm: vs agent
p = 0.030, vs agent+objective p = 0.035, vs random p = 0.18 (random is still
only 10 pairs). The within-campaign clean-vs-attacked column is the best
powered comparison and is the one to read.

## 3. Why the agent lost

Delay actually flown:

| method | delays |
|---|---|
| search | 0.15, then **0.25 for rounds 3-10** |
| agent | **0.05 in all 10 rounds** |

The agent returned `delay_band: "low"` in 8 of the 8 rounds where it issued an
intent (rounds 5 and 10 were confirmation repeats, which bypass the model by
design). `low` maps to {0.0, 0.05}, so the intent capped the ranker at the
minimum delay for the entire campaign.

Its own hypotheses show what it was doing: "temporary occlusion", "continuous
occlusion", "when the occlusion begins", "large, continuous visual occlusion".
It investigated the patch for ten rounds.

The controlled repeat blocks had already measured both factors:

| condition | pass rate | vs clean |
|---|---|---|
| clean | 9/15 = 0.60 | - |
| patch 0.3 m only | 8/15 = 0.53 | p = 1.00 |
| delay 0.25 + patch 0.9 m | 3/15 = 0.20 | p = 0.060 (p = 0.0012 vs pooled baseline) |

So the agent spent its whole budget on the factor with no measured effect and
never touched the one that works. The ranker underneath is the same code that,
unconstrained, found 7 candidates. **The intent filter actively harmed the
search.**

## 4. The objective was never stated, and stating it changes the behaviour

The system prompt told the model what it could not do and gave it a schema. It
never said what the campaign was for. The model inferred a characterisation
task.

`WS2_AGENT_STATE_OBJECTIVE=1` appends one sentence: find conditions where the
attacked flight fails while its clean control passes, and prefer untried,
more severe settings. Everything else is identical.

| | agent | agent + objective |
|---|---|---|
| `delay_band` chosen | low x8 | high x2, medium x3, low x2 |
| delays flown | 0.05 x10 | 0.25 x3, 0.15 x4, 0.05 x3 |
| candidates | 3 | 5 |
| attacked pass | 0.60 | 0.30 |

Round 1 went straight to the maximum delay: *"The most severe attack settings
will cause the drone to fail."*

The behavioural change is categorical and certain.

The performance change is not. At 10 pairs it looked large, 0.60 to 0.30,
Fisher p = 0.37. Extending to 18 pairs it regressed to 0.50, p = 0.71 against
the plain agent. **Stating the objective changes what the agent does without
improving what it finds.** Both agent arms remain significantly worse than
search.

This is the clearest illustration in the whole run of why the earlier campaigns
could not be trusted: the same apparent effect that survives at n=10 disappears
at n=18.

## 5. Two bugs this surfaced, both ours

Neither appeared in the pilot, because the pilot's agent arm never survived past
round 3.

1. **The 240-character limit was never enforced.** `intent_prompt_schema()`
   declares `maxLength: 240`, but the schema travels as data in the user message
   and `response_format: json_object` only enforces valid JSON, not the schema.
   Gemini 2.5 Pro overran it in 2 of 3 sampled replies (256, 269 characters),
   which aborts the campaign. Fixed by restating the limit as an instruction.
2. **The model was offered layouts it could not fly.** The schema exposed all
   three difficulty tiers while only `easy:2` was qualified. Choosing `medium`
   passes validation and then filters to zero actions, aborting the run. 2 of 4
   sampled replies chose `medium`. Fixed by narrowing the schema enum to the
   tiers that actually have actions, and the error now names the intent.

Both are prompt/schema faithfulness bugs: the contract shown to the model did
not match the contract enforced on its reply.

## 6. What this does not show

- Nothing here is about Kim. Kim has 6 archived flights and 1 attacked flight,
  and no qualified layout.
- Only `easy:2` was qualified, so the agent's `layouts` field had one option and
  contributed nothing. Its only real levers were delay band and patch mode.
- Random is still only 10 pairs, so search vs random (p = 0.18) is not resolved
  even though search vs both agent arms is.
- Why the agent underperforms is established. Whether a better-specified agent
  could beat the plain ranker is not: only one phrasing of the objective was
  tried, on one scene, with one model.
