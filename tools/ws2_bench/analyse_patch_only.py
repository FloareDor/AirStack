"""Paired analysis of a campaign.py run, which lays out cells as NNN_clean /
NNN_perturbed rather than the agent campaign's round_NN/<planner>/<role>.

Same discipline as analyse_kim_paired.py: the pair is the unit, McNemar over
discordant pairs only, and the twin is checked rather than assumed.
"""
import json, pathlib, sys
from math import comb

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SUCC = {"goal_reached", "completed_horizon"}
VOID = {"infrastructure_error"}


def load(cell, name):
    f = ROOT / cell / "attempt_0" / name
    return json.loads(f.read_text()) if f.exists() else None


def mcnemar_exact(b, d):
    n = b + d
    if n == 0:
        return 1.0
    k = min(b, d)
    return min(1.0, 2.0 * sum(comb(n, i) for i in range(k + 1)) / (2.0 ** n))


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return (max(0.0, c - h), min(1.0, c + h))


ids = sorted({p.name.split("_")[0] for p in ROOT.iterdir() if p.is_dir()})
rows, voided, inert = [], 0, 0
for i in ids:
    rc, rp = load(i + "_clean", "result.json"), load(i + "_perturbed", "result.json")
    if rc is None or rp is None:
        continue
    if rc.get("outcome") in VOID or rp.get("outcome") in VOID:
        voided += 1
        continue
    sc, sp = load(i + "_clean", "scenario.json"), load(i + "_perturbed", "scenario.json")
    cc, cp = sc["condition"], sp["condition"]
    diff = {k for k in set(cc) | set(cp) if cc.get(k) != cp.get(k)}
    # The whole point of this cell is that ONLY the patch differs. If anything
    # else moved, the run did not test what it claims to test.
    if diff - {"name", "patch_enabled", "patch_size"}:
        print("WARNING %s differs beyond the patch: %s" % (i, sorted(diff)))
    if not diff:
        inert += 1
        continue
    rows.append((i, cp, rc.get("outcome"), rp.get("outcome")))

print("=== isolated patch cell: %d usable pairs ===" % len(rows))
if voided:
    print("dropped %d pair(s) with an infrastructure_error arm" % voided)
if inert:
    print("dropped %d pair(s) whose arms were identical" % inert)
print("")

for i, cp, c, p in rows:
    print("%s %s:%-2s sz=%-5s delay=%-5s clean=%-18s pert=%s" % (
        i, cp.get("layout"), cp.get("layout_seed"), round(cp.get("patch_size"), 2),
        cp.get("delay"), c, p))

b = sum(1 for _, _, c, p in rows if c in SUCC and p not in SUCC)
d = sum(1 for _, _, c, p in rows if c not in SUCC and p in SUCC)
cs = sum(1 for _, _, c, _ in rows if c in SUCC)
ps = sum(1 for _, _, _, p in rows if p in SUCC)
n = len(rows)
cl, ch = wilson(cs, n)
pl, ph = wilson(ps, n)
print("")
print("clean  %d/%d [%.2f,%.2f]" % (cs, n, cl, ch))
print("attack %d/%d [%.2f,%.2f]" % (ps, n, pl, ph))
print("discordant b=%d d=%d   McNemar p=%.4f" % (b, d, mcnemar_exact(b, d)))
