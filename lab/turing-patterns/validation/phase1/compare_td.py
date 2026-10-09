"""Compare live captures using TD's bundled NumPy. Set PHASE1_ROOT first."""
import json
from pathlib import Path

import numpy as np

ROOT = Path(PHASE1_ROOT)
folder = ROOT / 'validation/phase1'
reports = [json.loads((folder / version / 'report.json').read_text()) for version in ('v1', 'v2')]
assert all(r.get('complete') for r in reports), 'Captures have not finished'
results = []
for path in sorted((folder / 'v1').glob('*.npz')):
    with np.load(str(path)) as a, np.load(str(folder / 'v2' / path.name)) as b:
        assert set(a.files) == set(b.files)
        for output in a.files:
            same_shape = a[output].shape == b[output].shape
            delta = float(np.max(np.abs(a[output] - b[output]))) if same_shape else None
            results.append({'capture': path.stem, 'output': output,
                            'shape_equal': same_shape, 'max_abs_error': delta,
                            'exact': same_shape and bool(np.array_equal(a[output], b[output]))})
structure = json.loads((folder / 'structure.json').read_text())
checks = {
    'all_pixels_exact': all(r['exact'] for r in results),
    'topology_and_builtin_parameters_equal': structure['v1_topology'] == structure['v2_topology'],
    'custom_parameters_equal': structure['v1_parameters'] == structure['v2_parameters'],
    'unique_names': structure['unique_names'] == ['turing_media_v2', 'turing_media_v2_2'],
    'no_unexpected_errors': all(not c['errors'] for r in reports for c in r['cases']),
    'all_finite': all(c['finite'] for r in reports for c in r['cases']),
    'all_cases_evolve': all(c['state_changed'] for r in reports for c in r['cases']),
    'pause_exact': all(c['pause_exact'] for r in reports for c in r['cases']),
    'reset_matches_seed': all(c['reset_matches_seed'] for r in reports for c in r['cases']),
    'chemicals_bounded': all(0 <= c['chemical_range'][0] <= c['chemical_range'][1] <= 1
                            for r in reports for c in r['cases']),
}
summary = {'build': reports[0]['build'], 'checks': checks,
           'comparisons': len(results), 'results': results}
(folder / 'comparison.json').write_text(json.dumps(summary, indent=2))
print('PHASE1_COMPARISON', checks, len(results))
assert all(checks.values()), 'Inspect comparison.json for failures'
