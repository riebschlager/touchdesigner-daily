from pathlib import Path
ROOT=Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
OUT=ROOT/'validation/phase7'
host=op('/project1').create(baseCOMP,'phase7_frames')
b=host.create(textDAT,'builder');b.text=(ROOT/'create_turing_media_v2.py').read_text()
ns=dict(globals(),me=b);exec(compile(b.text,'create_turing_media_v2.py','exec'),ns)
c=ns['turing_component'];d=host.create(textDAT,'frames');d.text=(OUT/'frames_td.py').read_text();d.module.start(c,str(OUT))
