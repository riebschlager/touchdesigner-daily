from pathlib import Path
ROOT=Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
host=op('/project1').create(baseCOMP,'phase7_profiler')
d=host.create(textDAT,'profile');d.text=(ROOT/'validation/phase7/profile_td.py').read_text();d.module.start('after','create_turing_media_v2.py')
