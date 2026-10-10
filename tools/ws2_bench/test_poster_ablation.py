"""The ablation's schedule, parsing and statistics.

The statistics are checked against scipy where scipy is available, because a
hand-rolled Mann-Whitney that is subtly wrong would not look wrong -- it would
just quietly produce a p-value, which is exactly how the two withdrawn interim
readings happened.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyse_poster_ablation as analyse
import poster_ablation


def test_schedule_is_balanced_and_rotates():
    arms = ['clean', 'fcrn_patch', 'phase_scrambled']
    plan = poster_ablation.schedule(arms, 5)
    assert len(plan) == 15
    for arm in arms:
        assert sum(a == arm for _, a in plan) == 5
    # Every round contains every arm exactly once, so stopping part way leaves a
    # balanced experiment rather than a biased one.
    for r in range(5):
        assert sorted(a for round_index, a in plan if round_index == r) == sorted(arms)
    # ...and the order is not the same every round, so no arm owns the
    # first-flight-after-restart slot.
    assert plan[0][1] != plan[3][1]


def test_a_part_finished_run_is_still_balanced_at_every_round_boundary():
    arms = ['clean', 'a', 'b', 'c']
    plan = poster_ablation.schedule(arms, 6)
    for rounds_done in range(1, 7):
        prefix = plan[:rounds_done*len(arms)]
        counts = {arm: sum(a == arm for _, a in prefix) for arm in arms}
        assert len(set(counts.values())) == 1, counts


def test_clean_arm_carries_no_poster_and_poster_arms_carry_theirs():
    clean = poster_ablation.build_episode('clean', 'mononav', 'easy', 2, 42, .9, 'x')
    assert clean['condition']['poster'] is None
    assert clean['condition']['patch_enabled'] is False
    for arm in ('fcrn_patch', 'phase_scrambled'):
        episode = poster_ablation.build_episode(arm, 'mononav', 'easy', 2, 42, .9, 'x')
        assert episode['condition']['poster'] == arm
        # Never via the attack axis, whatever the image is.
        assert episode['condition']['patch_enabled'] is False


def test_arms_differ_only_in_the_poster():
    clean = poster_ablation.build_episode('clean', 'mononav', 'easy', 2, 42, .9, 'x')['condition']
    patch = poster_ablation.build_episode('fcrn_patch', 'mononav', 'easy', 2, 42, .9, 'x')['condition']
    differing = {k for k in clean if clean[k] != patch[k]}
    assert differing == {'poster', 'name'}


def test_unknown_arm_is_refused():
    with pytest.raises(ValueError, match='unknown arm'):
        poster_ablation.build_episode('sharpened', 'mononav', 'easy', 2, 42, .9, 'x')


def test_correspondence_parsing_skips_unevaluated_frames(tmp_path):
    log = tmp_path/'worker.log'
    log.write_text(
        'frame=1 blocked=False zoe_corr=0.431/0.120 zoe_edges=5512 zoe=0.1s\n'
        'frame=2 blocked=False zoe_corr=1.000/0.120 zoe_edges=0 zoe=0.1s\n'
        'frame=3 blocked=False zoe_corr=0.090/0.120 zoe_edges=3100 zoe=0.1s\n'
        'startup noise with no frame line at all\n')
    values, skipped = analyse.frame_correspondences(log)
    # The zoe_edges=0 frame reports 1.0 by convention and carries no depth
    # information; counting it would drag the arm mean toward 1.0.
    assert values == [0.431, 0.090]
    assert skipped == 1


def test_missing_worker_log_is_not_fatal(tmp_path):
    assert analyse.frame_correspondences(tmp_path/'absent.log') == ([], 0)


@pytest.mark.parametrize('a,b', [
    ([.41, .38, .44, .40, .39, .42], [.21, .25, .19, .28, .23, .22]),
    ([.41, .38, .44, .40, .39, .42], [.40, .43, .37, .41, .38, .45]),
    ([.1, .2, .3, .4, .5, .5, .5], [.5, .5, .5, .6, .7, .8, .9]),
])
def test_mann_whitney_matches_scipy(a, b):
    scipy_stats = pytest.importorskip('scipy.stats')
    expected = scipy_stats.mannwhitneyu(a, b, alternative='two-sided', use_continuity=True,
                                        method='asymptotic')
    got = analyse.mann_whitney(a, b)
    assert got['p'] == pytest.approx(expected.pvalue, abs=1e-5)


def test_mann_whitney_declines_tiny_samples():
    assert analyse.mann_whitney([.1, .2], [.3, .4]) is None


@pytest.mark.parametrize('ap,an,bp,bn', [(12, 15, 6, 15), (15, 15, 9, 15), (8, 10, 8, 10), (118, 203, 100, 265)])
def test_fisher_matches_scipy(ap, an, bp, bn):
    scipy_stats = pytest.importorskip('scipy.stats')
    expected = scipy_stats.fisher_exact([[ap, an-ap], [bp, bn-bp]], alternative='greater')[1]
    assert analyse.fisher_one_sided(ap, an, bp, bn) == pytest.approx(expected, abs=1e-6)


def test_report_reads_arms_from_the_recorded_condition_not_the_folder_name(tmp_path):
    # Folder names are convenience; the condition is evidence. A run whose
    # folders were renamed must still analyse correctly.
    for name, poster, outcome, corr in [('000_anything', None, 'goal_reached', '0.400'),
                                        ('001_whatever', 'fcrn_patch', 'collision', '0.150')]:
        folder = tmp_path/name
        folder.mkdir()
        (folder/'result.json').write_text(json.dumps(
            {'outcome': outcome, 'metrics': {'minimum_obstacle_clearance_m': .05}}))
        (folder/'scenario.json').write_text(json.dumps(
            {'condition': {'poster': poster, 'layout': 'easy'}}))
        (folder/'worker.log').write_text(
            ''.join(f'frame={i} zoe_corr={corr}/0.120 zoe_edges=4000\n' for i in range(12)))
    result = analyse.report(tmp_path)
    assert set(result['arms']) == {'clean', 'fcrn_patch'}
    assert result['arms']['clean']['mean_zoe_corr'] == pytest.approx(.400)
    assert result['arms']['fcrn_patch']['mean_zoe_corr'] == pytest.approx(.150)
    assert result['arms']['clean']['pass_count'] == 1
    assert result['arms']['fcrn_patch']['pass_count'] == 0


def test_infrastructure_errors_are_excluded_from_both_endpoints(tmp_path):
    for name, outcome in [('000_clean', 'goal_reached'), ('001_clean', 'infrastructure_error')]:
        folder = tmp_path/name
        folder.mkdir()
        (folder/'result.json').write_text(json.dumps({'outcome': outcome, 'metrics': {}}))
        (folder/'scenario.json').write_text(json.dumps({'condition': {'poster': None}}))
        (folder/'worker.log').write_text('frame=1 zoe_corr=0.300/0.120 zoe_edges=4000\n')
    result = analyse.report(tmp_path)
    assert result['arms']['clean']['flights'] == 2
    assert result['arms']['clean']['usable'] == 1
    assert result['arms']['clean']['pass_n'] == 1
