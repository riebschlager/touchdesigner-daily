from pathlib import Path
ROOT=Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
exec(compile((ROOT/'validation/phase6/build_td.py').read_text(),'phase6_build','exec'))
validator=host.create(textDAT,'validate_phase6')
validator.text=(ROOT/'validation/phase6/validate_td.py').read_text()
validator.module.start(C,str(OUT))
