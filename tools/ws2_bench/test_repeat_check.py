"""Repeat-check summary must report rates, not stop at the first failure."""
import repeat_check


def _result(outcome, clearance, progress):
    return {"outcome": outcome, "configuration_hash": "abc",
            "metrics": {"minimum_obstacle_clearance_m": clearance,
                        "mission_progress_percent": progress}}


def test_stable_outcome_is_flagged_stable():
    summary = repeat_check.summarize([_result("goal_reached", 0.1, 93.8)] * 3)
    assert summary["outcome_is_stable"]
    assert summary["pass_rate"] == 1.0
    assert summary["metric_spread"]["minimum_obstacle_clearance_m"]["spread"] == 0.0


def test_flipped_outcome_is_not_stable_and_rate_is_partial():
    summary = repeat_check.summarize([_result("goal_reached", 0.10, 93.8),
                                      _result("collision", 0.01, 20.0),
                                      _result("goal_reached", 0.06, 93.9)])
    assert not summary["outcome_is_stable"]
    assert summary["pass_count"] == 2
    assert abs(summary["pass_rate"] - 2 / 3) < 1e-9
    spread = summary["metric_spread"]["minimum_obstacle_clearance_m"]
    assert abs(spread["spread"] - 0.09) < 1e-9
    assert spread["n"] == 3


def test_missing_metrics_are_skipped_not_counted_as_zero():
    results = [_result("goal_reached", 0.1, 93.8), {"outcome": "collision", "metrics": {}}]
    summary = repeat_check.summarize(results)
    assert "minimum_obstacle_clearance_m" not in summary["metric_spread"]
    assert summary["flights"] == 2


def test_clean_flag_forces_delay_and_patch_off():
    action = {"layout": "easy", "layout_seed": 2, "delay_s": 0.15,
              "patch_enabled": True, "patch_size_m": 0.9}
    episode = repeat_check.build_episode(action, "mononav", 42, True, "x")
    assert episode["condition"]["delay"] == 0.0
    assert episode["condition"]["patch_enabled"] is False


def test_attacked_episode_keeps_the_requested_delay_and_patch():
    action = {"layout": "easy", "layout_seed": 2, "delay_s": 0.15,
              "patch_enabled": True, "patch_size_m": 0.9}
    episode = repeat_check.build_episode(action, "mononav", 42, False, "x")
    assert episode["condition"]["delay"] == 0.15
    assert episode["condition"]["patch_enabled"] is True
    assert episode["condition"]["patch_size"] == 0.9
    assert episode["condition"]["rgb_noise"] == 0.0
