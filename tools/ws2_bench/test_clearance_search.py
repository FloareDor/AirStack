import pytest

from clearance_search import solve


def box_to_plane(gap):
    """A hull whose nearest surface sits `gap` away: dilating by `gap` touches."""
    return lambda t: t >= gap


def test_gap_is_recovered_to_submillimetre():
    value, censored = solve(box_to_plane(0.42), -0.1, 5.)
    assert not censored
    assert abs(value - 0.42) < 1e-3


def test_contact_reads_zero():
    value, censored = solve(box_to_plane(0.), -0.1, 5.)
    assert not censored
    assert abs(value) < 1e-3


def test_penetration_reads_negative():
    # The hull has to shrink by 5cm before it stops overlapping, so it is 5cm
    # inside the surface. The old scalar envelope could not produce this.
    value, censored = solve(box_to_plane(-0.05), -0.1, 5.)
    assert not censored
    assert abs(value + 0.05) < 1e-3


def test_nothing_in_range_is_censored():
    value, censored = solve(lambda t: False, -0.1, 5.)
    assert censored
    assert value == 5.


def test_penetration_deeper_than_the_floor_saturates():
    # Overlapping even at the smallest probe. Report the floor, not a boundary
    # that was never bracketed.
    value, censored = solve(lambda t: True, -0.1, 5.)
    assert not censored
    assert value == -0.1


def test_floor_must_sit_below_maximum():
    with pytest.raises(ValueError):
        solve(lambda t: True, 1., 1.)


def test_monotone_predicate_is_never_probed_out_of_order():
    seen = []

    def hits(t):
        seen.append(t)
        return t >= 0.3

    solve(hits, -0.1, 5.)
    # Every probe stays inside the bracket, so a predicate that is only valid
    # over [floor, maximum] is never asked about anything outside it.
    assert all(-0.1 <= t <= 5. for t in seen)


def test_resolution_improves_with_iterations():
    coarse, _ = solve(box_to_plane(0.42), -0.1, 5., iterations=4)
    fine, _ = solve(box_to_plane(0.42), -0.1, 5., iterations=20)
    assert abs(fine - 0.42) < abs(coarse - 0.42)
