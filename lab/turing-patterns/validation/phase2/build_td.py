"""Run in Textport; build into a fresh validation component without saving the TOE."""
from pathlib import Path
ROOT = Path(PHASE2_ROOT)
phase2_host = op('/project1').create(baseCOMP, 'phase2_validation')
phase2_runner = phase2_host.create(textDAT, 'builder')
phase2_runner.text = (ROOT / 'create_turing_media_v2.py').read_text()
phase2_namespace = dict(globals(), me=phase2_runner)
exec(compile(phase2_runner.text, 'create_turing_media_v2.py', 'exec'), phase2_namespace)
phase2 = phase2_namespace['turing_component']
phase2.par.Pause = True
print('PHASE2_BUILD', phase2.path, phase2.errors(recurse=True))
