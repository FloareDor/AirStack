"""Recover where the obstacles are from the clearance field.

No artifact records an obstacle position in world coordinates. layouts.json
stores offsets from source prims, the USD stage is not kept beside the results,
and layout_description only names the props. So the replay had nothing real to
draw and fell back to plotting crash sites.

But every pose sample carries clearance_m, the PhysX distance from the drone to
the nearest collider. That is a constraint, not just a number:

  * nothing lies within clearance_m of that position  ->  carve free space
  * something lies at exactly clearance_m             ->  vote on that ring

Pooled over 137k samples the free space carves out the room and the rings
intersect on the furniture. This is trilateration with a veto: a ring vote only
survives where no sample has ever proved the cell free.

One correction matters. Clearance counts the floor, so a drone at 1.25 m with
nothing beside it reads about 1.0 m no matter how open the room is. Those
samples carry no lateral information, so they carve free space but cast no vote.
"""
import glob
import json
import os

import numpy as np
from scipy import ndimage

RES = 0.08              # metres per cell
ENVELOPE = 0.25         # the 0.25 m sphere PhysX already subtracted
FLOOR_MARGIN = 0.08     # how far below the floor distance counts as "lateral"
RING_TOL = 0.10         # ring thickness, metres
MAX_R = 1.25            # ignore constraints beyond this; they are floor-limited
FREE_WEIGHT = 3.0       # how much one "empty" reading outweighs one surface vote
MIN_VOTES = 8.0         # a cell needs this many surface votes before it counts


def _disc(radius_cells):
    n = int(np.ceil(radius_cells))
    y, x = np.ogrid[-n:n + 1, -n:n + 1]
    return (x * x + y * y) <= radius_cells * radius_cells


def _annulus(radius_cells, tol_cells):
    outer = _disc(radius_cells + tol_cells)
    n = outer.shape[0] // 2
    inner_r = max(0.0, radius_cells - tol_cells)
    inner = _disc(inner_r)
    m = inner.shape[0] // 2
    pad = np.zeros_like(outer)
    pad[n - m:n + m + 1, n - m:n + m + 1] = inner
    return outer & ~pad


def samples(paths):
    """(x, y, clearance, lateral) for every usable pose sample."""
    xs, ys, cs, lat = [], [], [], []
    for sj in paths:
        try:
            rows = json.load(open(sj))
        except Exception:
            continue
        for s in rows:
            p, c = s.get("position_m"), s.get("clearance_m")
            if not (isinstance(p, list) and len(p) == 3 and isinstance(c, (int, float))):
                continue
            if c <= 0.0:
                continue
            xs.append(p[0]); ys.append(p[1]); cs.append(min(c + ENVELOPE, MAX_R))
            # the floor sits at z=0, and PhysX already removed the envelope
            lat.append(c < (p[2] - ENVELOPE) - FLOOR_MARGIN)
    return (np.array(xs), np.array(ys), np.array(cs), np.array(lat, dtype=bool))


def build(paths, pad=1.5):
    x, y, c, lateral = samples(paths)
    if not len(x):
        return None
    x0, x1 = x.min() - pad, x.max() + pad
    y0, y1 = y.min() - pad, y.max() + pad
    nx, ny = int((x1 - x0) / RES) + 1, int((y1 - y0) / RES) + 1
    ix = np.clip(((x - x0) / RES).astype(int), 0, nx - 1)
    iy = np.clip(((y - y0) / RES).astype(int), 0, ny - 1)

    free = np.zeros((ny, nx), dtype=np.float32)   # how often a cell was proved empty
    ring = np.zeros((ny, nx), dtype=np.float32)   # how often a surface was placed here

    # Quantise the radii so each distinct disc is built once.
    bins = np.clip((c / RES / 2).astype(int), 1, None)
    for b in np.unique(bins):
        m = bins == b
        r_cells = float(b) * 2.0
        hits = np.zeros((ny, nx), dtype=np.float32)
        np.add.at(hits, (iy[m], ix[m]), 1.0)
        free += ndimage.convolve(hits, _disc(r_cells).astype(np.float32),
                                 mode="constant", cval=0.0)

        ml = m & lateral
        if ml.any():
            votes = np.zeros((ny, nx), dtype=np.float32)
            np.add.at(votes, (iy[ml], ix[ml]), 1.0)
            ring += ndimage.convolve(votes, _annulus(r_cells, RING_TOL / RES).astype(np.float32),
                                     mode="constant", cval=0.0)

    # A surface vote competes with the evidence that the cell is empty, rather
    # than being vetoed outright by it. One noisy clearance reading should not
    # erase an obstacle that a hundred other samples agree on.
    occupied = ring / (ring + FREE_WEIGHT * free + 1e-6)
    occupied[ring < MIN_VOTES] = 0.0
    if occupied.max() > 0:
        occupied = occupied / occupied.max()
    seen = free > 0
    known = ndimage.binary_dilation(seen, structure=_disc(MAX_R / RES))
    return {"occ": occupied, "free": seen, "known": known,
            "extent": (x0, x0 + nx * RES, y0, y0 + ny * RES), "n": len(x)}


def grid_from_artifacts(art_dir, where=None):
    paths = glob.glob(os.path.join(art_dir, "**", "samples.json"), recursive=True)
    if where:
        paths = [p for p in paths if where(p)]
    return build(paths)


if __name__ == "__main__":
    import sys
    art = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "artifacts")
    g = grid_from_artifacts(art)
    occ = g["occ"]
    print("samples %d   grid %dx%d @ %.2f m" % (g["n"], occ.shape[1], occ.shape[0], RES))
    print("free cells      %d" % g["free"].sum())
    print("occupied >0.3   %d" % (occ > 0.3).sum())
    print("extent x %.1f..%.1f  y %.1f..%.1f" % g["extent"])
