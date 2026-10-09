"""Pure-Python scheduling tests; no TouchDesigner or external packages needed."""
import ast
import math
from pathlib import Path
import random
import unittest

ROOT = Path(__file__).resolve().parents[2]
TREE = ast.parse((ROOT / 'create_turing_media_v2.py').read_text())
CLOCK = next(ast.literal_eval(node.value) for node in TREE.body
             if isinstance(node, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'CLOCK_CALLBACKS' for t in node.targets))
namespace = {}
exec(compile(CLOCK, '<embedded clock>', 'exec'), namespace)
plan = namespace['plan_ticks']
TICK = namespace['TICK_SECONDS']


class ClockTests(unittest.TestCase):
    def sequence(self, durations, speed=1, realtime=False, limit=4):
        total, debt = 0, 0
        for elapsed in durations:
            count, debt = plan(debt, elapsed, speed, realtime, limit)
            total += count
        return total, debt

    def test_output_rates_and_fractional_speed(self):
        for fps in (24, 30, 60, 120, 240):
            for speed in (.125, .5, 1, 2, 8):
                ticks, debt = self.sequence([1 / fps] * (fps * 8), speed)
                self.assertEqual(ticks, round(480 * speed))
                self.assertAlmostEqual(debt, 0, places=9)

    def test_jitter_preserves_time(self):
        rng = random.Random(42)
        durations = [rng.uniform(.001, .08) for _ in range(10000)]
        ticks, debt = self.sequence(durations)
        self.assertAlmostEqual(ticks*TICK+debt, sum(durations), places=9)
        self.assertLess(debt, TICK)

    def test_catchup_is_bounded_without_discarding_time(self):
        ticks, debt = plan(0, 1, 1, True, 3)
        self.assertEqual(ticks, 3)
        self.assertAlmostEqual(debt, .95)
        while debt > 1e-10:
            count, debt = plan(debt, 0, 1, True, 3)
            self.assertLessEqual(count, 3)
            ticks += count
        self.assertEqual(ticks, 60)

    def test_offline_does_not_use_realtime_cap(self):
        self.assertEqual(plan(0, 1, 8, False, 1)[0], 480)

    def test_fractional_frames_do_not_evolve_early(self):
        count, debt = plan(0, TICK / 2, 1, False, 4)
        self.assertEqual(count, 0)
        self.assertEqual(plan(debt, TICK / 2, 1, False, 4)[0], 1)

    def test_negative_elapsed_cannot_rewind(self):
        self.assertEqual(plan(TICK / 2, -1, 1, False, 4), (0, TICK / 2))

    def test_embedded_python_compiles(self):
        for node in TREE.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if any(isinstance(t, ast.Name) and t.id.endswith('CALLBACKS') for t in node.targets):
                    compile(node.value.value, '<callback>', 'exec')


if __name__ == '__main__':
    unittest.main()
