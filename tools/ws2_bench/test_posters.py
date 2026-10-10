"""The poster axis must stay separable from the patch axis, in both directions.

These guard the bookkeeping that makes the ablation reportable: that a control
really is matched to the learned patch, that the digests are reproducible, and
above all that granting MonoNav `scene_poster` did not quietly hand it back the
`fcrn_patch` capability that `a82d18182` took away.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conditions import POSTERS, validate
from model_adapters import validate_attacks

HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE/'assets/controls/control_manifest.json').read_text())
CONTROLS = sorted(MANIFEST['controls'])


def test_every_registered_poster_exists_and_matches_its_recorded_digest():
    # A campaign cites these digests in provenance. If the file on disk drifts
    # from the manifest, every poster flight silently becomes unreplayable.
    for name, relative in POSTERS.items():
        path = HERE/relative
        assert path.exists(), f'{name} is registered but missing at {relative}'
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        recorded = (MANIFEST['controls'][name]['sha256'] if name in MANIFEST['controls']
                    else json.loads((HERE/'assets/patch_manifest.json').read_text())['sha256'])
        assert digest == recorded, f'{name} differs from its manifest'


def test_controls_regenerate_byte_identically():
    import make_control_posters
    fresh = make_control_posters.generate(out=HERE/'assets/controls_regenerated')
    try:
        for name in CONTROLS:
            assert fresh['controls'][name]['sha256'] == MANIFEST['controls'][name]['sha256'], \
                f'{name} is not reproducible from the learned patch and the recorded seed'
    finally:
        for leftover in (HERE/'assets/controls_regenerated').glob('*'):
            leftover.unlink()
        (HERE/'assets/controls_regenerated').rmdir()


@pytest.mark.parametrize('name', ['phase_scrambled', 'pixel_shuffled'])
def test_structure_free_controls_keep_the_learned_patch_colour_statistics(name):
    # The ablation only means something if the control differs from the learned
    # patch in structure and not in how bright or how colourful it is.
    learned, control = MANIFEST['learned_patch'], MANIFEST['controls'][name]['statistics']
    assert control['mean_rgb'] == pytest.approx(learned['mean_rgb'], abs=0.6)
    assert control['std_rgb'] == pytest.approx(learned['std_rgb'], abs=0.6)
    assert control['mean_luminance'] == pytest.approx(learned['mean_luminance'], abs=0.6)
    # Scrambling redistributes edge energy upward rather than removing it, so a
    # control is never the *gentler* image. That direction is what makes a null
    # result interpretable: if the learned patch hurts more than a control that
    # carries more local contrast, appearance alone does not explain it.
    assert control['mean_abs_gradient'] >= learned['mean_abs_gradient']


def test_flat_grey_keeps_the_mean_and_drops_all_contrast():
    learned, flat = MANIFEST['learned_patch'], MANIFEST['controls']['flat_grey']['statistics']
    assert flat['mean_luminance'] == pytest.approx(learned['mean_luminance'], abs=0.6)
    assert flat['std_luminance'] == 0
    assert flat['mean_abs_gradient'] == 0


def test_mononav_may_fly_posters_including_the_learned_image():
    for name in POSTERS:
        assert validate_attacks('mononav', validate({'layout': 'easy', 'layout_seed': 2, 'poster': name}))


def test_granting_mononav_scene_poster_did_not_restore_the_patch_capability():
    # The whole point of using a separate axis. If this ever passes, the
    # a82d18182 finding has been reversed by accident.
    with pytest.raises(ValueError, match='ZoeDepth'):
        validate_attacks('mononav', validate({'layout': 'easy', 'layout_seed': 2, 'patch_enabled': True}))


def test_kim_is_not_registered_for_poster_studies():
    # Kim's question is the attack one, on the model the patch was built for.
    # Flying it under scrambled controls would mix the two programmes.
    with pytest.raises(ValueError, match='scene_poster'):
        validate_attacks('kim', validate({'layout': 'easy', 'layout_seed': 2, 'poster': 'phase_scrambled'}))


@pytest.mark.parametrize('bad', [
    {'poster': 'not_a_poster'},
    {'poster': 'phase_scrambled', 'patch_enabled': True},
    {'poster': 'phase_scrambled', 'layout': 'stock'},
])
def test_invalid_poster_conditions(bad):
    with pytest.raises(ValueError):
        validate(dict({'layout': 'easy', 'layout_seed': 2}, **bad))


def test_poster_defaults_off_so_historical_conditions_are_unchanged():
    assert validate({'layout': 'easy', 'layout_seed': 2})['poster'] is None


@pytest.mark.parametrize('name,factor', [('contrast_50', .5), ('contrast_25', .25)])
def test_contrast_dose_series_keeps_the_mean_and_scales_only_the_amplitude(name, factor):
    # The dose arm must differ from the patch in amplitude and nothing else:
    # same mean colour, and a luminance sd scaled by exactly the factor. If the
    # mean moved too, a dose effect could be a brightness effect.
    learned, dosed = MANIFEST['learned_patch'], MANIFEST['controls'][name]['statistics']
    assert dosed['mean_luminance'] == pytest.approx(learned['mean_luminance'], abs=.6)
    assert dosed['mean_rgb'] == pytest.approx(learned['mean_rgb'], abs=.6)
    assert dosed['std_luminance'] == pytest.approx(learned['std_luminance']*factor, rel=.02)
    assert dosed['mean_abs_gradient'] == pytest.approx(learned['mean_abs_gradient']*factor, rel=.02)


def test_the_dose_series_is_monotone_in_contrast():
    sd = {n: MANIFEST['controls'][n]['statistics']['std_luminance']
          for n in ('flat_grey', 'contrast_25', 'contrast_50')}
    assert 0 == sd['flat_grey'] < sd['contrast_25'] < sd['contrast_50'] < MANIFEST['learned_patch']['std_luminance']
