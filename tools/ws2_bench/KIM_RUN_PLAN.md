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

## Kim has no qualified layout, and that is the first blocker

Everything flown so far:

| set | flights | outcomes |
|---|---|---|
| ws2_qualify_kim_easy1 | 4 | 4 completed_horizon |
| ws2_kim_random_easy1_aborted | 1 | 1 collision, on clean validation |
| kim_smoke_2 | 1 | 1 insufficient_progress |

`easy:1` passed 4 for 4 once and then killed a run by colliding on a clean
validation flight. Six flights cannot qualify a layout.

**Phase 1** flies clean blocks of 12 on `easy:1` and `easy:2` and picks the one
whose clean rate leaves room for an attack to show. A layout that is already
near the floor cannot demonstrate anything, which is the mistake I nearly made
with MonoNav this morning when 13 flights read 0.15.

Budget: 24 flights, about an hour.

## Phase 2 interleaves the controls

`run_kim_paired.sh` alternates control and attack blocks of 12, seven of each,
168 flights. Every attack block has a control block on both sides of it.

This is the direct fix for what pilot-10 got wrong. That run put a clean cell
first and last, they agreed at p = 1.000, and a third clean cell flown later
came back 0.750 against their 0.42. The timed-patch cell flown in between
inherited the shift and read as a large effect that `check_drift.py` now shows
is not there. Controls at the ends cannot see a change outside the region they
bracket.

Verify after the run, not before quoting anything:

```bash
python3 tools/ws2_bench/check_provenance.py artifacts/kim/*/     # same build
python3 tools/ws2_bench/check_drift.py artifacts/kim/kim_clean_* # stable baseline
```

`check_drift.py` exits 1 if the control blocks disagree more than chance
explains. If it does, pool only adjacent blocks and say so.

## Budget

A 12 hour window, minus roughly 2 hours of setup because Kim needs its own
repository, image build and two model downloads.

| phase | flights | time |
|---|---|---|
| qualification | 24 | ~1.0 h |
| paired campaign | 168 | ~7.0 h |
| copy out | | 0.5 h |

About 8.5 hours of a 10 hour flying budget, leaving real margin. Kim's 120 s
timeout is shorter than MonoNav's 180 s, so per-flight cost should be at or
below the 2.5 minutes pilot-10 averaged.

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
- [ ] `KIM_LAYOUT_SEED` set from phase 1, not guessed
- [ ] GPU recorded in provenance (`host.gpus` non-null; added 2026-10-04)
- [ ] Driver launched once, under `nohup`, for the whole campaign
- [ ] Nothing written into the AirStack tree after the first flight
