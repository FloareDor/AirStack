"""Bracket the dilation at which a vehicle hull first touches the scene.

Kept free of pxr and omni imports so it can be tested off the simulator. The
oracle supplies `hits`, a predicate over a dilation `t`: the vehicle's collider
box grown by `t` on every side overlaps something external. Growing a box only
ever adds overlap, so `hits` is monotonically non-decreasing in `t` and the
boundary can be bracketed.

The value returned is a real distance in the direction of closest approach:
positive is a gap between the hull and the nearest surface, zero is contact,
negative is penetration. That is what the previous scalar envelope could not
express, because it subtracted the hull's longest diagonal in every direction
at once and so reported penetration on flights that never touched anything.
"""


def solve(hits, floor, maximum, iterations=16):
    """Return (clearance, censored).

    `floor` is the most negative dilation worth probing, normally just inside
    the box's smallest half-extent, below which the shrunken box is degenerate.
    `censored` marks a reading saturated at `maximum`: nothing was within reach,
    so the true clearance is only known to be at least that far.
    """
    if floor >= maximum:
        raise ValueError('floor must be below maximum')
    if not hits(maximum):
        return maximum, True
    # Even the smallest box we are willing to probe is already overlapping, so
    # the penetration is deeper than this method can resolve. Report the floor
    # rather than a boundary that was never bracketed.
    if hits(floor):
        return floor, False
    lo, hi = floor, maximum
    for _ in range(iterations):
        mid = (lo + hi) / 2
        if hits(mid):
            hi = mid
        else:
            lo = mid
    return lo, False
