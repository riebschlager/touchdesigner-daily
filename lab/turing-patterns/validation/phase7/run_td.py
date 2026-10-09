from pathlib import Path
ROOT=Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
OUT=ROOT/'validation/phase7'
host=op('/project1').create(baseCOMP,'phase7_validation')
builder=host.create(textDAT,'builder');builder.text=(ROOT/'create_turing_media_v2.py').read_text()
ns=dict(globals(),me=builder);exec(compile(builder.text,'create_turing_media_v2.py','exec'),ns)
C=ns['turing_component'];C.op('clock').par.active=False;C.par.Pause=True
validator=host.create(textDAT,'validate');validator.text=(OUT/'validate_td.py').read_text();validator.module.start(C,str(OUT))
