"""Run before/after serially; close other busy projects for the cleanest measurement."""
from pathlib import Path
import json
ROOT=Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
OUT=ROOT/'validation/phase7'
host=op('/project1').create(baseCOMP,'phase7_profiler_final')
d=host.create(textDAT,'profile');d.text=(OUT/'profile_td.py').read_text()
for label in ('before','after'):(OUT/('profile_'+label+'.json')).unlink(missing_ok=True)
d.module.start('before','reference_v6.py')
def after_reference():
 if (OUT/'profile_before.json').exists():
  d.module.start('after','create_turing_media_v2.py')
 else:run('args[0]()',after_reference,delayFrames=30)
after_reference()
