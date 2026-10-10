"""Validated, replayable Office condition data, shared by simulator and runner."""
import math

DIFFICULTY_COUNTS={'easy':1,'medium':3,'hard':5}
PATCH_HEIGHT_M=1.2
PATCH_POLICY='original_texture_size_only_v1'

# The poster axis is NOT the patch axis, and the distinction is the whole point
# of it. patch_enabled asserts an adversarial attack is being run against a
# planner whose depth model the patch was optimised against; model_adapters
# gates it behind the fcrn_patch capability and refuses it for MonoNav, because
# the image is Kim's. poster asserts only that some image hangs on the column,
# with no claim whatever about efficacy, and exists so that the learned patch
# can be compared against structure-free controls with matched appearance. A
# poster result is a perception measurement and must never be reported as an
# attack result. See make_control_posters.py for how the controls are derived.
POSTERS={'fcrn_patch':'assets/learned_patch.png',
         'phase_scrambled':'assets/controls/phase_scrambled.png',
         'pixel_shuffled':'assets/controls/pixel_shuffled.png',
         'flat_grey':'assets/controls/flat_grey.png',
         'contrast_50':'assets/controls/contrast_50.png',
         'contrast_25':'assets/controls/contrast_25.png'}
POSTER_POLICY='scene_texture_no_efficacy_claim_v1'


def validate(raw):
    if not isinstance(raw, dict):
        raise ValueError("condition must be a mapping")
    if {'patch_strength','patch_height'} & raw.keys():
        raise ValueError('Legacy patch controls are unsupported: use patch_enabled and patch_size only. '
                         'Start a new campaign; historical settings/results must not be silently converted.')
    allowed = {"name", "layout", "layout_seed", "seed", "light", "rgb_noise", "depth_noise", "delay", "patch_enabled", "patch_size", "placement", "poster"}
    if set(raw) - allowed:
        raise ValueError(f"unknown condition fields: {set(raw) - allowed}")
    c = dict(name="clean", layout="furnished_a", layout_seed=0, seed=42, light=1800., rgb_noise=0.,
             depth_noise=0., delay=0., patch_enabled=False, patch_size=.8, poster=None)
    c.update(raw)
    if not isinstance(c["name"], str) or not c["name"].strip():
        raise ValueError("condition name required")
    if c["layout"] not in ("stock", "furnished_a", "furnished_b", "generated",*DIFFICULTY_COUNTS):
        raise ValueError("unsupported layout")
    maximum_seed=2**31-1 if c['layout']=='generated' else 7
    if isinstance(c["layout_seed"], bool) or not isinstance(c["layout_seed"], int) or not 0<=c["layout_seed"]<=maximum_seed:
        raise ValueError("layout_seed must select one of the validated layouts, 0..7")
    if c['layout']=='generated':
        from generated_layouts import validate_placement
        p=validate_placement(c.get('placement'))
        if p['parameters']['seed']!=c['layout_seed']:raise ValueError('Placement seed does not match condition')
    elif 'placement' in c:raise ValueError('Explicit placement requires generated layout')
    if isinstance(c["seed"], bool) or not isinstance(c["seed"], int) or not 0 <= c["seed"] < 2**31:
        raise ValueError("seed must be a nonnegative 31-bit integer")
    if not isinstance(c["patch_enabled"], bool):
        raise ValueError("patch_enabled must be boolean")
    for name, limits in {"light": (100, 6000), "rgb_noise": (0, 80), "depth_noise": (0, 2),
                         "delay": (0, 2), "patch_size": (.1, .95)}.items():
        value = c[name]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not limits[0] <= value <= limits[1]:
            raise ValueError(f"{name} must be in {limits}")
        c[name] = float(value)
    if c["patch_enabled"] and c["layout"] == "stock":
        raise ValueError("patch requires the added column in a furnished layout")
    if c["poster"] is not None:
        if c["poster"] not in POSTERS:
            raise ValueError(f"unknown poster {c['poster']!r}; registered: {sorted(POSTERS)}")
        if c["patch_enabled"]:
            # One quad, one image. Allowing both would leave which of the two
            # was actually rendered decided by whichever branch ran last, and a
            # poster run and a patch run make different claims about the result.
            raise ValueError("poster and patch_enabled both set; the column carries one image")
        if c["layout"] == "stock":
            raise ValueError("poster requires the added column in a furnished layout")
    return c


def sensor_parameters(c):
    return {"disturbance_seed": c["seed"], "rgb_noise_stddev": c["rgb_noise"],
            "depth_noise_stddev_m": c["depth_noise"], "fixed_sensor_delay_s": c["delay"]}
