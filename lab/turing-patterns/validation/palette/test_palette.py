"""Offline validation of response handling; run with Python's standard library."""
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SOURCE = runpy.run_path(str(ROOT / 'create_color_palette.py'))
R = {}
exec(SOURCE['RUNTIME'], R)


class PaletteTests(unittest.TestCase):
    def test_embedded_scripts_compile(self):
        for name in ('RUNTIME', 'CHOP_CALLBACKS', 'CONTROL_CALLBACKS', 'POLL_CALLBACKS'):
            compile(SOURCE[name], name, 'exec')

    def test_hex_inputs(self):
        for value, expected in [('#abc', 'AABBCC'), ('24b1e0', '24B1E0')]:
            self.assertEqual(R['normalize_hex'](value), expected)
        for value in ('', '12345', 'GGGGGG', 'https://example.com'):
            with self.assertRaises(ValueError):
                R['normalize_hex'](value)

    def test_response_validation(self):
        result = R['parse_palette']({'colors': [{'hex': {'value': '#FF0000'}}]}, 1)
        self.assertEqual(result, [('FF0000', 'FF0000')])
        for payload in (None, {}, {'colors': []}, {'colors': [{'hex': {'value': 'xyz'}}]}):
            with self.assertRaises((ValueError, KeyError)):
                R['parse_palette'](payload, 1)

    def test_network_failure_is_returned_as_data(self):
        q = R['queue'].Queue()
        with patch.object(R['urllib'].request, 'urlopen', side_effect=OSError('offline')):
            R['_worker']('https://www.thecolorapi.com/scheme', 5, 42, q)
        token, colors, error = q.get_nowait()
        self.assertEqual((token, colors, error), (42, None, 'offline'))

    def test_failure_retains_palette_and_stale_result_is_ignored(self):
        R['_pending'] = (100, R['time'].monotonic())
        q = R['_results']
        q.put((99, [('FF0000', 'Red')], None))
        q.put((100, None, 'offline'))
        messages = []
        old = R['status']
        R['status'] = lambda c, message: messages.append(message)
        old_apply = R['apply']
        R['apply'] = lambda *args: self.fail('Failure must not replace colors')
        try:
            R['poll'](object())
        finally:
            R['status'], R['apply'] = old, old_apply
        self.assertIsNone(R['_pending'])
        self.assertEqual(messages, ['Request failed; keeping palette: offline'])


if __name__ == '__main__':
    unittest.main()
