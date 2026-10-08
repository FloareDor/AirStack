# MonoNav fails clean flights about one time in five

Date: 2026-10-08. Workspace: OSMO `ws2-pilot-12`. AirStack `88ca77b7`,
MonoNav `86aba05`. All flights below are **clean conditions**: no patch, no
added sensor delay.

## The measurement

Fifteen flights of three saved scenarios, flown with the unmapped-gap gate off
(the configuration that flies normally), pooled across three campaigns in one
workspace and build:

| scenario | collisions | rate | sequence |
|---|---|---|---|
| `finding1_agent_round3` | 1/5 | 20% | goal, goal, goal, goal, collision |
| `finding1_random_round2` | 1/5 | 20% | goal, goal, goal, collision, goal |
| `finding2_easy0` | 5/5 | **100%** | collision ×5 |

Overall 7/15 = 47%, but the scenarios are not alike: one fails always and two
fail intermittently at roughly one flight in five.

## Why this matters more than any result it was collected for

**A clean control that fails 20% of the time cannot anchor a paired
comparison at the sample sizes used so far.** The guarded campaigns fly four
clean/attack pairs. With p(clean failure) = 0.2, the chance that at least one
of four clean controls fails by itself is 1 - 0.8^4 = 59%. The design treats a
clean failure as a reason to discard the pair, so most campaigns were
discarding pairs for a reason that had nothing to do with the attack.

It also explains the pattern every prior baseline reported and none explained:
a candidate failure is found, the confirmation flight passes, and the campaign
concludes the sample was too small. At a 20% base rate that is the expected
outcome of flying one confirmation. The candidates were not weak attack
effects failing to replicate; a fair share of them were the baseline failure
rate being read as a finding. This run shows it directly: in the second chunk
one arm collided on one scenario and the other arm collided on a different
one, with the only difference between the arms being a gate that never fired.

## Consequences for the bench

- **A pass/fail comparison needs far more pairs than four.** Separating a real
  attack effect from a 20% clean rate at any useful confidence takes tens of
  pairs per arm, not four. This is the strongest argument yet for scoring a
  continuous quantity, where every flight carries information, rather than a
  binary outcome where most flights carry almost none.
- **Confirmation flights must be repeated.** One repeat cannot distinguish a
  reproducible failure from a 20% coin flip. `run_gate_validation.py` now
  defaults to three repeats; three is a floor, not a sufficient number.
- **Report the clean failure rate alongside every result.** A campaign that
  does not state its own baseline failure rate cannot be interpreted later.

## `finding2_easy0` is different and should be treated separately

It collides on every flight, in a clean condition, against
`/World/Office/WS2_plant/SM_Plant01`, with `blocked=False` and
`depth_ok=True` on every frame up to contact. That is a deterministic planner
bug and needs no statistics at all — it needs a cause. It is by far the most
tractable target in this project right now, and it is unaffected by either
depth-confidence gate.

## What this does not say

These are three saved scenarios in one Office layout on one build. The 20%
figure is from five flights each; its confidence interval is wide and it
should be re-measured with more flights before being quoted as a number. What
is solid is the qualitative point: the clean failure rate is high enough to
dominate small paired campaigns, and it was never being measured.

Evidence: `artifacts/ws2_gate_validation/`, `artifacts/ws2_zoe_ab_1/`,
`artifacts/ws2_zoe_ab_2/`.
