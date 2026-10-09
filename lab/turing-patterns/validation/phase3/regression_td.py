"""Run in Textport after build_td.py. Reuse Phase 2 checks against a fresh Phase 3 build."""
phase3_regression_host = op('/project1').create(baseCOMP, 'phase3_clock_regression')
phase3_regression_builder = phase3_regression_host.create(textDAT, 'builder')
phase3_regression_builder.text = (ROOT/'create_turing_media_v2.py').read_text()
phase3_regression_namespace = dict(globals(),me=phase3_regression_builder)
exec(compile(phase3_regression_builder.text,'create_turing_media_v2.py','exec'),phase3_regression_namespace)
phase3_regression_component = phase3_regression_namespace['turing_component']
phase3_regression_component.op('clock').par.active = False
phase3_regression_test = phase3_regression_host.create(textDAT,'validate')
phase3_regression_test.text = (ROOT/'validation/phase2/validate_td.py').read_text()
phase3_regression_test.module.start(phase3_regression_component, str(ROOT/'validation/phase3/clock_regression'))
