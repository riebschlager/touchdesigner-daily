from pathlib import Path
ROOT=Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
exec(compile((ROOT/'validation/phase8/build_td.py').read_text(),'phase8_build','exec'))
validator=host.create(textDAT,'frames')
validator.text=(ROOT/'validation/phase8/frames_td.py').read_text()
validator.module.start(C,str(ROOT/'validation/phase8'))
