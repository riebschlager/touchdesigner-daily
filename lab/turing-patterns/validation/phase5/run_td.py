"""In Textport: exec(compile(open('/absolute/path/validation/phase5/run_td.py').read(), 'phase5', 'exec'))."""
exec(compile(open('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns/validation/phase5/build_td.py').read(), 'phase5_build', 'exec'))
validator=host.create(textDAT,'validate_phase5')
validator.text=(OUT/'validate_td.py').read_text()
validator.module.start(C,str(OUT))
