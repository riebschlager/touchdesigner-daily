"""Run with ordinary Python: prove the phase-1 refactor preserves V1 code."""
import ast
from contextlib import redirect_stdout
import hashlib
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_SHA256 = '35cdaf8e19c849b4316b8678e355b13bc0715a357734440a55c757b975ae0aba'


def main():
    reference = (ROOT / 'create_turing_media.py').read_bytes()
    assert hashlib.sha256(reference).hexdigest() == REFERENCE_SHA256, 'V1 changed'
    sources = [reference.decode(), (ROOT / 'create_turing_media_v2.py').read_text()]
    namespaces = []
    for source in sources:
        namespace = {}
        with redirect_stdout(io.StringIO()):
            exec(compile(source, '<builder>', 'exec'), namespace)
        namespaces.append(namespace)
    a, b = namespaces
    compared = []
    for name, value in a.items():
        if name.isupper() and name != 'NETWORK_HELP':
            assert b[name] == value, name
            compared.append(name)
    assert b['COMPONENT_BASENAME'] == 'turing_media_v2'
    compile(b['CONTROL_CALLBACKS'], '<callbacks>', 'exec')
    functions = [{n.name: n for n in ast.parse(s).body if isinstance(n, ast.FunctionDef)}
                 for s in sources]
    for name, original in functions[0].items():
        updated = functions[1]['build_turing_media_v2' if name == 'build_turing_media' else name]
        if name == 'build_turing_media':
            normalized = ast.unparse(updated).replace('build_turing_media_v2', 'build_turing_media')
            normalized = normalized.replace('COMPONENT_BASENAME', "'turing_media'")
            normalized = normalized.replace("'{}_{}'.format('turing_media', suffix)",
                                            "'turing_media_{}'.format(suffix)")
            updated = ast.parse(normalized).body[0]
        assert ast.dump(original) == ast.dump(updated), name
    print('PASS: V1 hash, {} constants/shaders/callbacks, {} construction/helper functions.'
          .format(len(compared), len(functions[0])))


if __name__ == '__main__':
    main()
