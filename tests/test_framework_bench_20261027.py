"""Safety and data isolation for the optional experimental harness."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
P=Path(__file__).resolve().parents[1]/'scripts/framework_bench_20261027.py'
spec=importlib.util.spec_from_file_location('framework_bench',P);b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
class BenchmarkTests(unittest.TestCase):
    def test_duplicate_framework_callback_cannot_dispatch(self):
        with tempfile.TemporaryDirectory(dir=P.parents[1]/'data/qa') as d:
            g=b.Gateway(Path(d),True);g.call([],b.Reading)
            with self.assertRaisesRegex(RuntimeError,'no_extra_dispatch'):g.call([],b.Reading)
            self.assertEqual(g.calls,1)
    def test_unknown_never_retried(self):
        with tempfile.TemporaryDirectory(dir=P.parents[1]/'data/qa') as d:
            g=b.Gateway(Path(d),True);g.pending=1
            with self.assertRaises(RuntimeError):g.call([],b.Reading)
            self.assertEqual(g.calls,0)
    def test_stage_budget_not_purchase_quota(self):
        with tempfile.TemporaryDirectory(dir=P.parents[1]/'data/qa') as d:
            g=b.Gateway(Path(d),True)
            for _ in range(2):g.stage_called=False;g.call([],b.Reading)
            g.stage_called=False
            with self.assertRaises(RuntimeError):g.call([],b.Reading)
    def test_holdout_balanced(self):
        self.assertEqual(sum(x[2] for x in b.CASES),3)
        self.assertEqual({x[3] for x in b.CASES},{'CH6','CH7','CH8'})
    def test_wrong_output_shape_rejected(self):
        with self.assertRaises(Exception):b.Verdicts.model_validate({'findings':[]})
        with self.assertRaises(Exception):b.Finding.model_validate({'id':'H1','supported':'true','source_ids':['CH6-P001'],'reason':'x'})
    def test_closed_transport_rejects_even_new_stage(self):
        with tempfile.TemporaryDirectory(dir=P.parents[1]/'data/qa') as d:
            g=b.Gateway(Path(d),True);g.closed=True;g.stage_called=False
            with self.assertRaises(RuntimeError):g.call([],b.Reading)
if __name__=='__main__':unittest.main()
