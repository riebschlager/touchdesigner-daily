from pathlib import Path
import json
ROOT=Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
OUT=ROOT/'validation/phase5'
C=op(json.loads((OUT/'build.json').read_text())['path'])
test=C.parent().create(textDAT,'frame_validate')
test.text=(OUT/'frames_td.py').read_text()
test.module.start(C,str(OUT))
