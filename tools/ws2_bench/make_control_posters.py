"""Derive non-adversarial control posters from the learned patch.

The learned patch is a bright, high-contrast 128x128 image. Two separate things
could change a planner's behaviour when it is hung on the column:

  1. its adversarial structure -- the specific spatial arrangement of pixels
     that an attack optimised against a depth model, or
  2. its ordinary appearance -- a bright, saturated, high-contrast rectangle
     where the wall used to be plain.

A control poster holds (2) fixed and removes (1). Each control below keeps some
first-order appearance statistic of the learned patch exactly, while destroying
the spatial structure that an optimisation could have put there:

  phase_scrambled  identical per-channel histogram and (to within the final
                   histogram match) identical amplitude spectrum; the Fourier
                   PHASE is replaced with that of white noise. Same colours,
                   same spatial frequency content, no aligned structure. This
                   is the primary control: it is the closest possible image
                   that cannot be carrying an optimised pattern.
  pixel_shuffled   identical per-channel histogram, spectrum destroyed as well.
                   The 'same colours, no structure at all' bound.
  flat_grey        the per-channel mean, zero contrast. The 'is it merely a
                   bright rectangle' bound.

Determinism is the point: the derivation is a pure function of the learned
patch bytes and SEED, so a control can be regenerated and its sha256 rechecked
by anyone replaying a campaign. Regenerating must reproduce the recorded
digests exactly; if it does not, a run used a different image than it claims.

Nothing here asserts that any poster, learned or control, degrades any planner.
That is what the flights and the depth sensitivity study measure.
"""
import argparse, hashlib, json
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SOURCE = HERE/'assets/learned_patch.png'
OUT = HERE/'assets/controls'
SEED = 20261010
# Same phase field for every channel: scrambling each channel independently
# produces chromatic confetti, which is a different image statistic, not a
# control. One shared field keeps the channels registered with each other.


def _match_histogram(values, reference):
    """Remap values onto reference's exact multiset, preserving rank order."""
    order = np.argsort(values, axis=None, kind='stable')
    out = np.empty(values.size, dtype=np.float64)
    out[order] = np.sort(reference, axis=None, kind='stable')
    return out.reshape(values.shape)


def phase_scrambled(rgb, rng):
    phase = np.angle(np.fft.fft2(rng.normal(size=rgb.shape[:2])))
    out = np.empty_like(rgb, dtype=np.float64)
    for channel in range(rgb.shape[2]):
        amplitude = np.abs(np.fft.fft2(rgb[:, :, channel]))
        scrambled = np.fft.ifft2(amplitude*np.exp(1j*phase)).real
        out[:, :, channel] = _match_histogram(scrambled, rgb[:, :, channel])
    return out


def pixel_shuffled(rgb, rng):
    flat = rgb.reshape(-1, rgb.shape[2])
    return flat[rng.permutation(flat.shape[0])].reshape(rgb.shape)


def flat_grey(rgb, rng):
    return np.broadcast_to(rgb.reshape(-1, rgb.shape[2]).mean(axis=0), rgb.shape).copy()


DERIVATIONS = {'phase_scrambled': phase_scrambled, 'pixel_shuffled': pixel_shuffled,
               'flat_grey': flat_grey}
# Statistics a control is supposed to preserve, checked and recorded rather
# than asserted in prose. luminance is Rec. 709.
LUMINANCE = np.array([.2126, .7152, .0722])


def statistics(rgb):
    luminance = rgb @ LUMINANCE
    return {'mean_rgb': [round(float(v), 4) for v in rgb.reshape(-1, rgb.shape[2]).mean(axis=0)],
            'std_rgb': [round(float(v), 4) for v in rgb.reshape(-1, rgb.shape[2]).std(axis=0)],
            'mean_luminance': round(float(luminance.mean()), 4),
            'std_luminance': round(float(luminance.std()), 4),
            'min_luminance': round(float(luminance.min()), 4),
            'max_luminance': round(float(luminance.max()), 4),
            # Mean absolute Sobel-ish gradient: how much local edge energy the
            # image carries. ZoeDepth reads edges, so a control that matched
            # colour but not this would not be a fair comparison.
            'mean_abs_gradient': round(float(
                (np.abs(np.diff(luminance, axis=0)).mean()+np.abs(np.diff(luminance, axis=1)).mean())/2), 4)}


def generate(seed=SEED, out=OUT, source=SOURCE):
    expected = json.loads((HERE/'assets/patch_manifest.json').read_text())
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected['sha256']:
        raise ValueError('Source patch differs from assets/patch_manifest.json; controls must derive from the registered image')
    rgb = np.asarray(Image.open(source).convert('RGB'), dtype=np.float64)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {'derived_from': {'filename': source.name, 'sha256': expected['sha256']},
                'seed': seed, 'generator': 'make_control_posters.py',
                'claim': 'Scene texture only. No attack efficacy is claimed or implied for any poster here, learned or control.',
                'learned_patch': statistics(rgb), 'controls': {}}
    for name, derive in sorted(DERIVATIONS.items()):
        # A fresh generator per control: adding or reordering a control must not
        # change the bytes of the others.
        # int.from_bytes(sha256(name)) rather than hash(name): str hashing is
        # salted per process, so hash() would give different bytes every run.
        stream = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], 'big')
        derived = np.clip(derive(rgb, np.random.default_rng([seed, stream])), 0, 255)
        image = np.rint(derived).astype(np.uint8)
        path = out/f'{name}.png'
        Image.fromarray(image).save(path, optimize=True)
        manifest['controls'][name] = dict(
            filename=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            width=image.shape[1], height=image.shape[0],
            description=derive.__doc__ or DERIVATIONS[name].__name__,
            statistics=statistics(image.astype(np.float64)))
    (out/'control_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--seed', type=int, default=SEED)
    p.add_argument('--check', action='store_true',
                   help='Regenerate and fail if any digest differs from the recorded manifest')
    a = p.parse_args()
    if a.check:
        recorded = json.loads((OUT/'control_manifest.json').read_text())
        fresh = generate(seed=a.seed)
        differing = [n for n, c in fresh['controls'].items()
                     if recorded['controls'].get(n, {}).get('sha256') != c['sha256']]
        if differing or recorded['seed'] != fresh['seed']:
            raise SystemExit('Control posters are not reproducible: '+', '.join(differing or ['seed']))
        print(json.dumps({'reproducible': sorted(fresh['controls'])}, indent=2))
    else:
        print(json.dumps(generate(seed=a.seed), indent=2))
