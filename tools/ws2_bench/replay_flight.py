"""Animate WS2 flights top-down from the per-flight pose samples.

A flight that stored samples.json (sim_time, position, PhysX clearance) and
scene_status.json (the object the oracle recorded contact with, and where) can
be replayed without the camera stream, which the bench never recorded.

Mission mode matters to the picture. MonoNav flies 'goal': the goal and its
capture radius are drawn. Kim flies 'avoidance' and has no goal at all, so the
panel says so rather than leaving the reader to wonder where it went.
"""
import glob
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from matplotlib.colors import LinearSegmentedColormap

import occupancy as occmap

# Confidence must read as more solid, not less. copper_r sent the strongest
# cells to black, which reads as a hole in the floor rather than a wall.
SURFACE = LinearSegmentedColormap.from_list(
    "ws2_surface", ["#f7e3d2", "#e89a63", "#c05f33", "#8c3418"])

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "artifacts")
OUT = os.path.join(ART, "replays")

INK, PAPER = "#131a24", "#f8f9fb"
ACCENT, SIGNAL, MUTED, GOAL = "#15567f", "#a6442a", "#9aa5b4", "#1f7a4d"

FRAMES, FPS = 90, 14
NEAR_M = 0.35          # clearance at or below this is drawn as a near miss
SUCC = {"goal_reached", "completed_horizon"}


def load_all():
    out = []
    for sj in glob.glob(os.path.join(ART, "**", "samples.json"), recursive=True):
        d = os.path.dirname(sj)
        if not all(os.path.exists(os.path.join(d, f))
                   for f in ("result.json", "scenario.json", "mission.json")):
            continue
        try:
            cond = json.load(open(os.path.join(d, "scenario.json")))["condition"]
            res = json.load(open(os.path.join(d, "result.json")))
            mis = json.load(open(os.path.join(d, "mission.json")))
            raw = json.load(open(sj))
        except Exception:
            continue
        s = [x for x in raw if isinstance(x.get("position_m"), list) and len(x["position_m"]) == 3]
        if len(s) < 50:
            continue
        col = {}
        ssp = os.path.join(d, "scene_status.json")
        if os.path.exists(ssp):
            col = (json.load(open(ssp)).get("oracle") or {}).get("collision") or {}
        out.append({
            "dir": d,
            "run": os.path.relpath(d, ART).split(os.sep)[0],
            "planner": cond.get("planner") or ("kim" if mis.get("mode") == "avoidance" else "mononav"),
            "layout": cond.get("layout"),
            "seed": cond.get("layout_seed"),
            "attacked": bool(cond.get("patch_enabled") or cond.get("delay")
                             or cond.get("rgb_noise") or cond.get("depth_noise")),
            "patch_size": cond.get("patch_size") if cond.get("patch_enabled") else None,
            "outcome": res.get("outcome"),
            "mode": mis.get("mode"),
            "goal": mis.get("goal"),
            "radius": mis.get("radius"),
            "takeoff": mis.get("takeoff_sim_time"),
            "t": np.array([x["sim_time_s"] for x in s], dtype=float),
            "p": np.array([x["position_m"] for x in s], dtype=float),
            "c": np.array([x.get("clearance_m", np.nan) for x in s], dtype=float),
            "hit_obj": col["objects"][0].split("/")[-2] if col.get("objects") else None,
            "hit_pos": col.get("position"),
        })
    return out


_OCC = {}


def scene_map(fl, flight):
    """Obstacles inferred from the clearance field, for this flight's scene.

    Must be built per (layout, seed): the props move between variants, so
    pooling scenes lets one variant's flights carve another variant's furniture
    away as free space. Validated against held-out crash sites, the per-scene
    map puts a surface within 0.5 m of the recorded contact point for 89-100%
    of collisions; the pooled version managed 3%.
    """
    key = (flight["layout"], flight["seed"])
    if key not in _OCC:
        paths = [os.path.join(f["dir"], "samples.json") for f in fl
                 if (f["layout"], f["seed"]) == key]
        _OCC[key] = occmap.build(paths) if paths else None
    return _OCC[key]


def extent(panels, pad=1.6):
    xs, ys = [], []
    for f, _ in panels:
        xs += [f["p"][:, 0].min(), f["p"][:, 0].max()]
        ys += [f["p"][:, 1].min(), f["p"][:, 1].max()]
        if f["goal"]:
            xs.append(f["goal"][0]); ys.append(f["goal"][1])
    x0, x1, y0, y1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    # equal aspect without letting one axis collapse
    cx, cy, half = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) / 2
    return (cx - half, cx + half), (cy - half, cy + half)


def draw(ax, f, upto, occ, label, xlim, ylim):
    ax.clear()
    ax.set_xlim(*xlim); ax.set_ylim(*ylim)
    ax.set_aspect("equal"); ax.set_facecolor(PAPER)
    for sp in ax.spines.values():
        sp.set_color(MUTED); sp.set_linewidth(0.8)
    ax.set_xticks([]); ax.set_yticks([])

    if occ:
        ax.imshow(occ["free"], origin="lower", extent=occ["extent"], cmap="Blues",
                  alpha=0.22, vmin=0, vmax=1.4, zorder=0, interpolation="nearest")
        ax.imshow(np.ma.masked_less(occ["occ"], 0.12), origin="lower", extent=occ["extent"],
                  cmap=SURFACE, alpha=0.9, vmin=0, vmax=1, zorder=1,
                  interpolation="nearest")

    p, c = f["p"], f["c"]
    start = p[0]

    # the goal, when the mission has one
    if f["goal"]:
        g, rad = f["goal"], (f["radius"] or 0.5)
        ax.plot([start[0], g[0]], [start[1], g[1]], color=GOAL, lw=1.0,
                ls=(0, (5, 4)), alpha=0.55, zorder=2)
        ax.add_patch(plt.Circle((g[0], g[1]), rad, facecolor=GOAL, alpha=0.18, zorder=2))
        ax.add_patch(plt.Circle((g[0], g[1]), rad, facecolor="none", edgecolor=GOAL,
                                lw=1.8, zorder=3))
        ax.text(g[0], g[1] + rad + 0.35, "GOAL  r=%.1fm" % rad, color=GOAL, fontsize=8,
                ha="center", va="bottom", family="monospace", weight="bold")
    else:
        ax.text(0.985, 0.975, "no goal\navoidance mission", transform=ax.transAxes,
                fontsize=8, family="monospace", color=MUTED, ha="right", va="top")

    n = max(2, upto)
    seg = p[:n]
    near = c[:n] <= NEAR_M
    ax.plot(seg[:, 0], seg[:, 1], color=ACCENT, lw=1.6, alpha=0.8, zorder=4)
    if near.any():
        ax.scatter(seg[near, 0], seg[near, 1], s=9, color=SIGNAL, alpha=0.85, zorder=5)

    ax.scatter([start[0]], [start[1]], s=70, marker="o", facecolor="none",
               edgecolor=INK, linewidths=1.4, zorder=6)
    ax.text(start[0], start[1] - 0.55, "start", color=INK, fontsize=7.5,
            ha="center", va="top", family="monospace")

    cur = p[n - 1]
    ax.scatter([cur[0]], [cur[1]], s=58, color=ACCENT, zorder=7,
               edgecolor="white", linewidths=1.0)

    done = n >= len(p)
    if done and f["hit_pos"] and f["outcome"] == "collision":
        hp = f["hit_pos"]
        ax.scatter([hp[0]], [hp[1]], s=170, marker="x", color=SIGNAL, linewidths=2.6, zorder=8)
        ax.text(hp[0], hp[1] + 0.45, f["hit_obj"], color=SIGNAL, fontsize=7.5,
                ha="center", va="bottom", family="monospace", weight="bold")

    flown = f["t"][n - 1] - (f["takeoff"] or f["t"][0])
    cl = c[n - 1]
    ax.set_title(label, color=INK, fontsize=10.5, family="monospace", loc="left", pad=8)
    ax.text(0.015, 0.975, "t+%5.1f s" % max(0.0, flown), transform=ax.transAxes,
            fontsize=8.5, family="monospace", color=INK, va="top")
    ax.text(0.015, 0.928, "clearance %.2f m" % cl, transform=ax.transAxes,
            fontsize=8.5, family="monospace", va="top",
            color=SIGNAL if np.isfinite(cl) and cl <= NEAR_M else INK)
    if f["goal"]:
        dg = float(np.hypot(cur[0] - f["goal"][0], cur[1] - f["goal"][1]))
        ax.text(0.015, 0.881, "to goal   %.2f m" % dg, transform=ax.transAxes,
                fontsize=8.5, family="monospace", color=GOAL, va="top")
    if done:
        ok = f["outcome"] in SUCC
        ax.text(0.015, 0.04, f["outcome"].replace("_", " ").upper(), transform=ax.transAxes,
                fontsize=10, family="monospace", weight="bold",
                color=(GOAL if f["goal"] else ACCENT) if ok else SIGNAL, va="bottom")


def render(panels, path, occs):
    xlim, ylim = extent(panels)
    fig, axes = plt.subplots(1, len(panels), figsize=(4.15 * len(panels), 4.5), dpi=96)
    axes = [axes] if len(panels) == 1 else list(axes)
    fig.patch.set_facecolor(PAPER)
    imgs = []
    for k in range(FRAMES):
        frac = (k + 1) / FRAMES
        for ax, (f, lab), occ in zip(axes, panels, occs):
            draw(ax, f, int(round(frac * len(f["p"]))), occ, lab, xlim, ylim)
        fig.tight_layout(pad=1.1)
        fig.canvas.draw()
        imgs.append(Image.frombuffer("RGBA", fig.canvas.get_width_height(),
                                     fig.canvas.buffer_rgba(), "raw", "RGBA", 0, 1)
                    .convert("RGB").quantize(colors=96, method=Image.Quantize.FASTOCTREE))
    plt.close(fig)
    imgs[0].save(path, save_all=True, append_images=imgs[1:] + [imgs[-1]] * int(FPS * 1.6),
                 duration=int(1000 / FPS), loop=0, optimize=True, disposal=2)
    return os.path.getsize(path)


def find(fl, prefer_success=False, **kw):
    hits = [f for f in fl if all(f.get(k) == v for k, v in kw.items() if v is not None)]
    if prefer_success:
        # A family that can be flown should be shown being flown. A family that
        # never succeeds has no success to show, and falls back honestly.
        hits = [f for f in hits if f["outcome"] in SUCC] or hits
    return hits[0] if hits else None


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    FL = load_all()
    print("replayable flights: %d  (kim %d, mononav %d)" % (
        len(FL), sum(f["planner"] == "kim" for f in FL), sum(f["planner"] == "mononav" for f in FL)))

    jobs = []

    # MonoNav: the attack working, with the goal drawn. Same round = same scene.
    rnd = os.path.join(ART, "ws2_search_mononav_guarded", "round_03")
    mc = find(FL, planner="mononav", attacked=False, outcome="goal_reached")
    ma = find(FL, planner="mononav", attacked=True, outcome="collision")
    for f in FL:
        if f["dir"].startswith(rnd) and not f["attacked"]:
            mc = f
        if f["dir"].startswith(rnd) and f["attacked"]:
            ma = f
    if mc and ma:
        jobs.append(([(mc, "MONONAV  clean       goal mission"),
                      (ma, "MONONAV  patch %.1f m  goal mission" % (ma["patch_size"] or 0))],
                     "pair_mononav_attack.gif"))

    # Kim: no goal exists, so the panel says so.
    ka = find(FL, planner="kim", layout="furnished_a", outcome="completed_horizon", attacked=False)
    kb = find(FL, planner="kim", layout="furnished_b", outcome="collision", attacked=False)
    if ka and kb:
        jobs.append(([(ka, "KIM  furnished_a  clean"), (kb, "KIM  furnished_b  clean")],
                     "pair_furnished_a_vs_b.gif"))

    for lay in ("furnished_a", "furnished_b", "easy", "medium", "hard"):
        f = find(FL, prefer_success=True, planner="kim", layout=lay, attacked=False)
        if f:
            jobs.append(([(f, "KIM  %s  clean  %s" % (lay, f["outcome"]))],
                         "family_%s.gif" % lay))

    for panels, name in jobs:
        occs = [scene_map(FL, f) for f, _ in panels]
        print("  %-30s %6.1f KB" % (name, render(panels, os.path.join(OUT, name), occs) / 1024.0))
