import challenge_layouts as cl
import scene_feasibility as sf
from generated_layouts import generate


def boxes_for(challenge, seed=42):
    return sf.layout_boxes(cl.generate_challenge(challenge, seed))


def test_empty_scene_has_room():
    assert sf.widest_clearance([]) > sf.MONONAV_MIN_DIST2OBS_M


def test_clearance_is_monotone_in_the_radius():
    boxes = boxes_for('slalom')
    room = sf.widest_clearance(boxes)
    assert sf.route_exists(boxes, room * .9)
    assert not sf.route_exists(boxes, room * 1.1 + .05)


def test_every_challenge_fits_the_vehicle_but_not_the_planner():
    # The point of the module. free_route certifies these because the drone
    # fits; MonoNav still rejects every primitive, so flying them measures the
    # planner's clearance rule rather than any attack.
    for challenge in cl.CHALLENGES:
        verdict = sf.assess(boxes_for(challenge))
        assert verdict['fits_physically'], challenge
        assert not verdict['planner_can_plan'], challenge
        assert verdict['widest_clearance_m'] < sf.MONONAV_MIN_DIST2OBS_M


def test_offset_gap_is_the_tightest_challenge():
    rooms = {c: sf.assess(boxes_for(c))['widest_clearance_m'] for c in cl.CHALLENGES}
    assert rooms['offset_gap'] == min(rooms.values())


def test_corridor_checked_generated_layout_leaves_planner_room():
    # The arm that flew 15/15 in the corridor A/B. Its obstacles are off the
    # route, so the planner has somewhere admissible to go.
    verdict = sf.assess(sf.layout_boxes(generate(42, 'easy')))
    assert verdict['planner_can_plan']


def test_assess_reports_the_numbers_it_judged_on():
    verdict = sf.assess([], required=.5, hull=.2)
    assert verdict['required_clearance_m'] == .5
    assert verdict['hull_radius_m'] == .2
