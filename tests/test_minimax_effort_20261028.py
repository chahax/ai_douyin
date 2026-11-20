import sys
import time
import unittest
from scripts.novel_minimax_effort_20261028 import parameters, bounded_process


class EffortContract(unittest.TestCase):
    def test_only_effort_differs(self):
        a, b = parameters('same source', 'medium'), parameters('same source', 'max')
        self.assertEqual(a.pop('reasoning_effort'), 'medium')
        self.assertEqual(b.pop('reasoning_effort'), 'max')
        self.assertEqual(a, b)
        self.assertNotIn('tools', a)
        self.assertTrue(a['stream'])

    def test_invalid_effort(self):
        with self.assertRaises(ValueError):
            parameters('text', 'none')

    def test_real_child_deadline(self):
        start = time.monotonic()
        code, expired = bounded_process([sys.executable, '-c', 'import time; time.sleep(30)'], .2)
        self.assertTrue(expired)
        self.assertLess(time.monotonic()-start, 5)

    def test_normal_child(self):
        code, expired = bounded_process([sys.executable, '-c', 'pass'], 5)
        self.assertEqual(code, 0)
        self.assertFalse(expired)


if __name__ == '__main__':
    unittest.main()
