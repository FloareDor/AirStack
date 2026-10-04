"""Paired analysis of the Kim campaign.

The unit of analysis is the PAIR, not the flight. Each round flies the same
layout twice, once clean and once perturbed, so layout difficulty cancels
within the pair. Pooling flights would re-introduce exactly the confound the
paired design exists to remove.

McNemar is the right test here: only discordant pairs carry information about
the attack. Concordant pairs (both pass, both fail) tell us about the layout,
not the perturbation. Exact binomial, because the discordant count is small.
"""
import json, pathlib, sys
from math import comb

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                    "/root/AirStack/robot/ros_ws/ws2_runtime/campaigns/kim_random_paired")
SUCC = {"goal_reached", "completed_horizon"}
# A flight that never really flew is not evidence about the attack. Dropping
# these is not cherry-picking: they are infrastructure failures, and they are
# reported separately below so the drop is auditable.
VOID = {"infrastructure_error"}


def load(rd, role, fname):
    f = rd / "kim" / role / "attempt_0" / fname
    return json.loads(f.read_text()) if f.exists() else None


def mcnemar_exact(b, d):
    """Two-sided exact McNemar. b = clean-pass/attack-fail (attack worked),
    d = clean-fail/attack-pass. Under H0 each discordant pair is a coin flip."""
    n = b + d
    if n == 0:
        return 1.0
    k = min(b, d)
    tail = sum(comb(n, i) for i in range(0, k + 1)) / (2.0 ** n)
    return min(1.0, 2.0 * tail)


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return (max(0.0, c - h), min(1.0, c + h))


rows, voided = [], 0
for rd in sorted(ROOT.glob("round_*")):
    rc, rp = load(rd, "clean", "result.json"), load(rd, "perturbed", "result.json")
    if rc is None or rp is None:
        continue
    oc, op = rc.get("outcome"), rp.get("outcome")
    if oc in VOID or op in VOID:
        voided += 1
        continue
    sp = load(rd, "perturbed", "scenario.json")
    sc = load(rd, "clean", "scenario.json")
    cond, ccond = sp["condition"], sc["condition"]
    # Guard the twin. An attack arm that is not actually perturbed is not a
    # test of anything, and silently averaging it in would bias toward null.
    differs = {k for k in set(cond) | set(ccond) if cond.get(k) != ccond.get(k)}
    rows.append(dict(round=rd.name, layout=cond.get("layout"),
                     seed=cond.get("layout_seed"), patch=cond.get("patch_enabled"),
                     size=cond.get("patch_size"), delay=cond.get("delay"),
                     start=sp.get("patch_start_s"), dur=sp.get("patch_duration_s"),
                     clean=oc, pert=op, differs=sorted(differs)))

inert = [r for r in rows if not r["differs"]]
rows = [r for r in rows if r["differs"]]


def report(label, sub):
    if not sub:
        return
    b = sum(1 for r in sub if r["clean"] in SUCC and r["pert"] not in SUCC)
    d = sum(1 for r in sub if r["clean"] not in SUCC and r["pert"] in SUCC)
    cs = sum(1 for r in sub if r["clean"] in SUCC)
    ps = sum(1 for r in sub if r["pert"] in SUCC)
    n = len(sub)
    p = mcnemar_exact(b, d)
    cl, ch = wilson(cs, n)
    pl, ph = wilson(ps, n)
    print("%-22s n=%-3d clean=%d/%d [%.2f,%.2f]  attack=%d/%d [%.2f,%.2f]  "
          "b=%d d=%d  McNemar p=%.4f" % (label, n, cs, n, cl, ch, ps, n, pl, ph, b, d, p))


print("=== Kim paired campaign: %d usable pairs ===" % len(rows))
if voided:
    print("dropped %d pair(s) with an infrastructure_error arm" % voided)
if inert:
    print("dropped %d pair(s) whose arms were identical" % len(inert))
print("")

report("ALL", rows)
print("")
print("--- by layout family (headroom check) ---")
for fam in sorted({r["layout"] for r in rows}):
    report(fam, [r for r in rows if r["layout"] == fam])

print("")
print("--- patch arm vs delay-only arm ---")
report("patch enabled", [r for r in rows if r["patch"]])
report("delay only", [r for r in rows if not r["patch"]])

print("")
print("--- continuous vs timed patch ---")
report("continuous", [r for r in rows if r["patch"] and not r["start"] and not r["dur"]])
report("timed", [r for r in rows if r["patch"] and (r["start"] or r["dur"])])

print("")
print("--- per-pair ---")
for r in rows:
    print("%-9s %-7s:%s patch=%-5s sz=%-4s delay=%-5s t=%s/%s  clean=%-18s pert=%s" % (
        r["round"], r["layout"], r["seed"], r["patch"], r["size"], r["delay"],
        r["start"], r["dur"], r["clean"], r["pert"]))
