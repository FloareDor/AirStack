"""How much room a layout actually leaves, measured against a given clearance.

challenge_layouts.free_route answers "does the vehicle fit", inflating obstacles
by a 0.35 m vehicle radius. That is the right question for collisions and its
docstring says so. It is not the question the planner asks: MonoNav rejects any
primitive within `min_dist2obs` of a mapped obstacle, 0.8 m by default. A layout
can pass free_route and still offer no trajectory the planner will accept.

So the same search is run here with the radius as a parameter, and
`widest_clearance` reports the largest clearance for which a route still exists.
Compare that against the planner's requirement before spending flights.

Important limit: this reasons about ground-truth geometry. The planner applies
its margin to what it has MAPPED. In this bench the two diverge sharply -- the
solid column and the plant both sit on the centreline in `easy` seed 2, and of
311 MonoNav collisions 311 are the plant and 0 are the column. The column is
seen and avoided; the plant never enters the TSDF. So a scene this module calls
unplannable will stop the planner only for obstacles it can actually see.
"""
from collections import deque

from generated_layouts import geometry

STEP = .2
# Source (x,y) = (-world_y, world_x), matching challenge_layouts.free_route.
START, GOAL = (0, -20), (0, 20)
HULL_RADIUS_M = .3482      # measured, see project clearance notes
MONONAV_MIN_DIST2OBS_M = .8


def route_exists(boxes, radius):
    """Is there a 2-D route from takeoff to goal keeping `radius` from `boxes`?"""
    floors = geometry()['floors']

    def free(node):
        x, y = (v * STEP for v in node)
        if not (-2.8 <= x <= 2.8 and -4.2 <= y <= 4.2):
            return False
        if not all(any(f[0][0] <= u <= f[1][0] and f[0][1] <= v <= f[1][1] for f in floors)
                   for u in (x - radius, x + radius) for v in (y - radius, y + radius)):
            return False
        return not any(b[0][2] < 1.55 and b[1][2] > .85 and
                       b[0][0] - radius <= x <= b[1][0] + radius and
                       b[0][1] - radius <= y <= b[1][1] + radius for b in boxes)

    if not free(START) or not free(GOAL):
        return False
    queue = deque([START]); seen = {START}
    while queue:
        node = queue.popleft()
        if node == GOAL:
            return True
        for dx, dy in ((0, 1), (1, 0), (-1, 0), (0, -1)):
            nxt = (node[0] + dx, node[1] + dy)
            if nxt not in seen and free(nxt):
                seen.add(nxt); queue.append(nxt)
    return False


def widest_clearance(boxes, maximum=2., iterations=18):
    """Largest radius for which a route still exists.

    Monotone: a route keeping r clear also keeps anything smaller clear, so the
    boundary can be bracketed the same way the oracle brackets its hull.
    """
    if not route_exists(boxes, 0.):
        return 0.
    lo, hi = 0., maximum
    for _ in range(iterations):
        mid = (lo + hi) / 2
        if route_exists(boxes, mid):
            lo = mid
        else:
            hi = mid
    return lo


def assess(boxes, required=MONONAV_MIN_DIST2OBS_M, hull=HULL_RADIUS_M):
    """Does the vehicle fit, and will the planner accept anything?"""
    room = widest_clearance(boxes)
    return {'widest_clearance_m': round(room, 3),
            'fits_physically': room >= hull,
            'planner_can_plan': room >= required,
            'required_clearance_m': required,
            'hull_radius_m': hull}


def layout_boxes(placement):
    """Scene boxes for a placement: fixed Office furniture plus placed obstacles."""
    g = geometry()
    moved = g['sources']['move']['path']
    boxes = [b for path, b in g['occupied'].items() if path != moved]
    return boxes + list(placement['bounds_source_m'].values())
