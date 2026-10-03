# The WS2 bench cannot yet tell an attack from noise

Date: 2026-10-02
Source: all 42 `result.json` files under `tools/ws2_bench/artifacts/`
Method: group every flight by its *physical* configuration, then compare flights
that share one. Any difference between them is the bench's own variance.

## 0. Summary

- The clean, unattacked MonoNav `easy:2` flight has been flown **19 times** and
  failed **3 times**. The baseline failure rate is **16%**, not zero.
- **Every** configuration that has been flown more than once flipped outcome.
  Five out of five.
- Pooling every MonoNav flight ever run, attacked flights fail 31% and clean
  flights fail 16%, which is **not distinguishable from chance** (Fisher exact,
  p = 0.40). No attack has yet been shown to do anything.
- At 4 attacked flights per arm, an arm reports at least one candidate failure
  **50% of the time from the clean baseline alone**. The pilot's 2/2/1 candidate
  counts are what pure noise looks like.
- The "0 of 5 candidates reproduced" claim rests on three flights that never
  left the start box, on an uncommitted planner tree that no longer exists.

## 1. `configuration_hash` does not identify a configuration

`fingerprint()` hashes the whole resolved episode, including the human-readable
`name` field and `patch_size` even when `patch_enabled` is false. So the clean
twin of agent round 1 (`795ef054f067`), the clean twin of agent round 3
(`b3a5b9b87266`) and the pristine clean validation flight (`034a48733b1a`) all
get different hashes while being the same flight: MonoNav, `easy:2`, seed 42,
no delay, no patch.

This is why nobody noticed the bench had flown the identical clean flight 19
times. Grouping on hash finds 4 repeated configurations. Grouping on physics
finds 5, covering 31 of the 39 comparable flights.

**Fix:** fingerprint only the physically meaningful fields, and drop patch
geometry and timing from the hash when the patch is off.

## 2. The clean baseline fails 16% of the time

MonoNav, `easy:2`, seed 42, no delay, no patch, 19 flights across every campaign:

| outcome | count |
|---|---|
| goal_reached | 16 |
| collision | 3 |

Pass rate 16/19 = 0.842, 95% Wilson interval [0.624, 0.945]. Minimum clearance
ranges from -0.003 m to 0.117 m, sd 0.037 m.

Every campaign treats a clean-twin failure as an infrastructure problem and
halts. It is not infrastructure. It is the expected behaviour of this planner on
this scene one time in six.

## 3. Every repeated configuration flipped

| configuration | n | pass rate | outcomes |
|---|---|---|---|
| mononav easy:2, no attack | 19 | 16/19 | goal_reached ×16, collision ×3 |
| kim easy:1, no attack | 4 | 3/4 | completed_horizon ×3, collision |
| mononav easy:2, delay 0.15, patch 0.3 m @10s/5s | 3 | 2/3 | goal_reached ×2, planner_stopped |
| mononav easy:2, delay 0.25, patch 0.9 m @5s/5s | 3 | 2/3 | goal_reached ×2, collision |
| mononav easy:2, delay 0.0, patch 0.3 m @5s/10s | 2 | 1/2 | goal_reached, collision |

Five configurations flown more than once, five flipped. Outcome is not a
function of configuration. Every campaign we have run flies each configuration
once and records the outcome as a property of that configuration, which on this
evidence is not sound.

## 4. The attacks have not been shown to do anything

Pooling all MonoNav flights outside `ws2_fix_validation`:

| | flights | failures | rate |
|---|---|---|---|
| attacked | 13 | 4 | 0.308 |
| clean | 19 | 3 | 0.158 |

Fisher exact p = **0.40**. The direction is right and the effect may well be
real, but at this sample size it is indistinguishable from the baseline.

With a 16% baseline failure rate and 4 attacked flights per arm, the chance of
an arm reporting at least one candidate from noise alone is **1 - 0.842^4 = 0.50**.
The pilot reported 2 candidates for random, 2 for search and 1 for the agent.
That is exactly the distribution the clean baseline produces by itself.

## 5. The ranking signal is the size of its own noise

The search ranker orders candidates by how close the previous round came to
failing, dominated by minimum obstacle clearance.

- Within the single clean configuration, 19 flights: clearance sd **0.037 m**.
- Across all 25 successful MonoNav flights of every configuration: sd **0.032 m**.

Run-to-run variance on a fixed configuration is as large as the spread across
every different configuration tried. Minimum clearance is a near-tangent
quantity, so timing jitter moves the closest approach a lot while the trajectory
barely changes (progress stayed within 93.8-93.9% and path length within
8.42-8.59 m on the 4-flight repeat). Ordering configurations by it, from one
flight each, is close to ordering noise.

Clearance is also signed: -0.009 m and -0.003 m were observed. It is a margin
against a 0.25 m envelope, not a distance.

## 6. The "0 of 5 reproduced" claim is unsupported and unreproducible

Three re-flights in `ws2_fix_validation` were read as evidence that candidate
failures do not repeat. All three ended identically:

| re-flight | outcome | progress | max displacement | recoveries |
|---|---|---|---|---|
| `finding1_agent_round3` | planner_stopped | 0.0 % | 0.105 m | 12 |
| `finding1_random_round2` | planner_stopped | 0.0 % | 0.058 m | 12 |
| `finding2_easy0` | planner_stopped | 0.0 % | 0.141 m | 12 |

`stationary_fraction` 1.0 in all three, stop reason
`no central safe primitive after 12 yaw scans`. The drone never left the start
box. These flights did not test whether anything repeats.

`provenance.json` says why. Same `worker_command.json` byte for byte, same
MonoNav commit `7de1f7a`, but:

| | original campaigns | the re-flights |
|---|---|---|
| `mononav.diff_sha256` | `e3b0c442...b855` | `9fb980fe...2fd7b` |
| `worker_image` | `sha256:e7fc6a9c...` | `sha256:cd21d274...` |

`e3b0c442...b855` is the sha256 of empty input, so the originals ran a clean
checkout. The re-flights ran uncommitted edits to `/root/MonoNav` with the image
rebuilt from them. Those were the two guards. They were never pushed, the branch
head is still `7de1f7a` dated 2026-09-28, and the workspace is gone. `depth_ok`
was true on every frame, so the depth guard never fired.

## What this changes

1. **Flights per configuration must be greater than one.** `repeat_check.py`
   measures the rate and never stops at the first failure, because a run that
   stops early cannot measure a rate.
2. **Measure the clean baseline first and report everything against it.** A
   candidate is only a candidate if the attacked failure rate exceeds 16%.
3. **Budget by power, not by round count.** Against a 0.84 baseline at
   alpha 0.05 and power 0.80:

   | attacked pass rate | flights per arm | per pair | wall clock at 5 min/flight |
   |---|---|---|---|
   | 0.70 | 137 | 274 | 23 h |
   | 0.60 | 53 | 106 | 8.8 h |
   | 0.50 | 29 | 58 | 4.8 h |
   | 0.40 | 18 | 36 | 3.0 h |
   | 0.30 | 12 | 24 | 2.0 h |

   An 8-flight budget can only resolve a near-total attack. Comparing three
   methods at that budget cannot work, whatever the methods do.
4. **Report a failure rate with an interval, not a candidate count.**
5. **Fix the fingerprint** so repeated flights are recognised as repeats.
6. **Refuse to run against a dirty planner tree**, or warn loudly.
   `provenance.json` already records `diff_sha256`; nothing checks it.
7. **Redo the re-flights** on the committed `7de1f7a` tree.
