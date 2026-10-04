# Kim et al. run plan

## Why this is the important run

The patch was trained against `config_depth_fcrn.yaml` (`assets/patch_manifest.json`),
and Kim runs `--depth-source fcrn` (`episode.py:80`). MonoNav runs ZoeDepth.

So every number in `artifacts/pilot10/` is a **transfer** attack, and Kim is the
matched target. A patch that costs ZoeDepth 28 points of success rate should
cost FCRN at least that much. If it does not, the transfer result is the more
surprising one and needs explaining.

## Kim is scored differently, and it is easy to get this wrong

Kim is avoidance mode, not goal mode (`mission.py:8-11`):

| | Kim | MonoNav |
|---|---|---|
| mission_mode | avoidance | goal |
| success | `completed_horizon` | `goal_reached` |
| timeout | 120 s | 180 s |
| speeds | 0.2 / 0.35 | 0.4 / 0.5 |

`completed_horizon` means it survived the horizon with at least 3 m travel and
1 m displacement. `goal_reached` is an **error** for Kim and `audit_results.py:19`
rejects it. `SUCCESSES` in `mission.py:4` already counts both, so the pass rate
is computed correctly, but any hand analysis that greps for `goal_reached` will
silently score Kim as zero.

## Superseded: the fixed-layout design, and why it was dropped

This plan originally qualified a layout and then flew 168 flights on it, seven
control blocks alternating with seven attack blocks. `run_kim_paired.sh` still
implements that and is kept as a fallback. It was not used, for two reasons
found on `ws2-pilot-11`.

**Kim flies at about 7 minutes per flight.** Measured from provenance
`started_at_utc`: 19:33 and 19:40 UTC, steady state rather than startup, and
2.8 times MonoNav despite a shorter timeout, so per-flight overhead dominates.
168 flights needs 20 hours. A 12 hour window cannot hold it, and the 24-flight
qualification alone would have cost 2.8 hours of an 11.4 hour remainder.

**The qualified-layout gate was standing in for pairing.**
`agent_campaign.py:250` already flies both arms of every candidate,
`clean_twin(candidate)` and `candidate`, in the same layout, the same build,
seconds apart. The gate exists for the unpaired case, where an attack flight is
compared against a baseline flown elsewhere and an unflyable layout is
indistinguishable from a successful attack. With pairing that failure mode is
gone, so the gate is a budget heuristic, not a correctness gate. At 7 minutes a
flight it is a heuristic that costs more than it saves.

A pair whose clean arm fails is then a scored outcome, "this layout is
unflyable", rather than contaminated data. Under the default
`--clean-failure-policy halt` that same event aborted an earlier Kim run on one
collision (`ws2_kim_random_easy1_aborted`).

## The run that was actually flown

```bash
python3 tools/ws2_bench/agent_campaign.py     --policy random --planner kim --budget 80 --seed 42     --qualified-layout easy:0 ... --qualified-layout hard:7     --clean-failure-policy record --clean-validation-runs 0     --review-seconds 0     --output robot/ros_ws/ws2_runtime/campaigns/kim_random_paired
```

All 24 layouts across `easy`, `medium` and `hard`. 80 flights is 40 matched
pairs, about 9.3 hours. No code change was needed: `--qualified-layout` is
repeatable and `--clean-failure-policy record` already existed. We had been
passing a one-element list to a filter built to take many.

**Analyse by pair, not by flight.** The attack worked where the clean arm
passed and the perturbed arm failed. McNemar over the discordant pairs. This is
immune to the three confounds that cost results on 2026-10-04: cross-build
(both arms, one workspace), time drift (both arms, adjacent), and layout
difficulty (both arms, same scene).

The tradeoff is real and worth stating: 40 pairs spread over 24 layouts gives
less power per layout than 168 flights on one. That buys an unbiased read on
whether the patch works on its matched target across the actual scene space,
instead of a precise answer about one office with three objects in it.

## Kim had no qualified layout, and now does not need one

Everything flown before this run:

| set | flights | outcomes |
|---|---|---|
| ws2_qualify_kim_easy1 | 4 | 4 completed_horizon |
| ws2_kim_random_easy1_aborted | 1 | 1 collision, on clean validation |
| kim_smoke_2 | 1 | 1 insufficient_progress |
| kim_qual_easy1 (pilot-11, abandoned) | 1 | 1 collision, clean |

`easy:1` passed 4 for 4 once, then collided on a clean flight twice in separate
runs. Six flights never qualified it, and under the paired design that question
no longer gates the run.

## Budget

Measured on `ws2-pilot-11`: about 7 minutes per Kim flight, against 2.5 for
MonoNav. Plan from the measurement, not from the timeout, because per-flight
overhead dominates both.

| phase | flights | time |
|---|---|---|
| setup (Kim repo, image, two models) | | ~2.0 h |
| paired campaign, 40 pairs | 80 | ~9.3 h |
| copy out | | 0.5 h |

That is most of a 12 hour window and leaves little slack, so copy cells down as
they complete rather than at the end. The OSMO task filesystem is ephemeral.

## Setup additions over the MonoNav runbook

`OSMO_PILOT_RUNBOOK.md` section 3 clones MonoNav only. Kim also needs:

```bash
git clone --recursive https://github.com/engcang/Collision-avoidance.git /root/Collision-avoidance
(cd /root/Collision-avoidance && bash docker/build_image.sh && bash docker/download_models.sh)
```

`download_models.sh` fetches the FCRN checkpoint. `save_model/D3QN_V_3_single.h5`
is already tracked in the repository (`BACKUP.md:52`).

**`unzip` must be installed first.** Without it `download_models.sh` downloads
450 MB, verifies the archive, then dies on line 22 with
`unzip: command not found` and leaves `NYU_FCRN-checkpoint` empty. On
`ws2-pilot-11` that killed the whole setup script. The runbook's apt line now
installs it. Verify three files, not a directory:

```bash
ls /root/Collision-avoidance/airstack_models/NYU_FCRN-checkpoint/
# NYU_FCRN.ckpt.data-00000-of-00001  NYU_FCRN.ckpt.index  NYU_FCRN.ckpt.meta
```

`run_kim_paired.sh` refuses to fly if either model is absent, for the same
reason the MonoNav driver does.

## Pre-submit checklist

- [ ] Kim image built and both models present
- [ ] All 24 layout selectors passed, not a one-element list
- [ ] GPU recorded in provenance (`host.gpus` non-null; added 2026-10-04)
- [ ] Driver launched once, under `nohup`, for the whole campaign
- [ ] Nothing written into the AirStack tree after the first flight
