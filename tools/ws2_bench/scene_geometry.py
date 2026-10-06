"""Absolute positions for the props that layouts.json only describes as offsets.

layouts.json records each added or moved prop as a translation from the prim it
was copied from, never as a place. The USD stage is not kept beside the results,
so for a long time nothing in the artifact tree said where an obstacle actually
was, and the replays had to fall back on plotting crash sites.

The source prims can be solved for. When a flight hits WS2_plant in variant 5,
the oracle records the contact point in world coordinates, and layouts.json
gives that prop's offset for variant 5. Subtracting one from the other
estimates the source prim, and 349 recorded contacts over many variants agree
on it to about 0.1 m. Every prop in all 40 variants then follows from

    position = source prim + offset

Checked against the same contacts: median error 0.11 m, 92 percent within 1 m.
The spread is the width of the prop itself, since a contact point lies on the
surface and the offset refers to the origin.

Only three source prims are needed. Every added plant is a copy of one plant,
every added column is a copy of one column, and 'move' is the existing plant
that gets shifted rather than duplicated.
"""
import collections
import glob
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = json.load(open(os.path.join(HERE, "layouts.json")))

# layout_summary.py maps a stored offset into world axes this way.
def to_world(offset):
    return np.array([offset[1], -offset[0], offset[2]], dtype=float)


def family_of(key):
    if key == "move":
        return "move_src"
    if key.startswith("plant"):
        return "plant_src"
    if key.startswith("column"):
        return "column_src"
    return None


def _contacts(art):
    for ss in glob.glob(os.path.join(art, "**", "scene_status.json"), recursive=True):
        sc = os.path.join(os.path.dirname(ss), "scenario.json")
        if not os.path.exists(sc):
            continue
        try:
            cond = json.load(open(sc))["condition"]
            col = (json.load(open(ss)).get("oracle") or {}).get("collision") or {}
        except Exception:
            continue
        if not (col.get("position") and col.get("objects")):
            continue
        yield (col["objects"][0].split("/")[-2],
               np.array(col["position"], dtype=float),
               cond.get("layout"), cond.get("layout_seed"))


def solve_sources(art=None):
    """Estimate each source prim from recorded contacts."""
    art = art or os.path.join(HERE, "artifacts")
    acc = collections.defaultdict(list)
    for name, pos, layout, seed in _contacts(art):
        entry = CATALOG.get(layout, [{}] * 8)[seed]
        if name.startswith("WS2_"):
            key = name[4:]
        elif name == "SM_Plant7_463":
            key = "move"        # the existing plant, shifted rather than copied
        else:
            continue
        fam = family_of(key)
        if fam and key in entry:
            acc[fam].append(pos - to_world(entry[key]))
    return {f: np.median(np.array(v), axis=0) for f, v in acc.items() if v}


def props(layout, seed, sources):
    """Every prop in one variant, as (name, world position)."""
    entry = CATALOG.get(layout, [{}] * 8)[seed]
    out = []
    for key, value in entry.items():
        if not (isinstance(value, list) and len(value) == 3):
            continue
        fam = family_of(key)
        if fam in sources:
            out.append((key, sources[fam] + to_world(value)))
    return out


def check(sources, art=None):
    """Hold the contacts up against the model that was fitted to them."""
    art = art or os.path.join(HERE, "artifacts")
    err = []
    for name, pos, layout, seed in _contacts(art):
        if not name.startswith("WS2_"):
            continue
        key = name[4:]
        entry = CATALOG.get(layout, [{}] * 8)[seed]
        fam = family_of(key)
        if fam in sources and key in entry:
            err.append(float(np.hypot(*(sources[fam] + to_world(entry[key]) - pos)[:2])))
    e = np.array(err)
    return {"n": len(e), "median": float(np.median(e)),
            "p90": float(np.percentile(e, 90)), "within_1m": float((e < 1.0).mean())}


if __name__ == "__main__":
    s = solve_sources()
    for k, v in sorted(s.items()):
        print("%-11s [%7.2f %7.2f %6.2f]" % (k, *v))
    r = check(s)
    print("\ncheck: n=%d  median %.2f m  p90 %.2f m  within 1 m %.0f%%"
          % (r["n"], r["median"], r["p90"], 100 * r["within_1m"]))
    for fam in ("furnished_a", "furnished_b", "easy", "medium", "hard"):
        print("%-12s variant 3: %d props" % (fam, len(props(fam, 3, s))))
