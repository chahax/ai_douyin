"""Compare an additional retained-receipt failure against hash-exact v20."""
from pathlib import Path
import os, sys, json, hashlib, socket, importlib.util
ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['LLM_PROVIDER']='mock'
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'legacy_diagnostic.sqlite3').replace(chr(92),'/')
def blocked(*args,**kwargs):raise RuntimeError('Offline legacy comparison prohibits networking')
socket.socket.connect=blocked
socket.socket.connect_ex=blocked
from src.content_factory.creative_workflow import CreativeWorkflow
import test_creative_real_receipt_replay as case
from test_creative_workflow import FakeClients
binding=json.loads((OUT/'baseline_v20_reconstruction.json').read_text())
assert binding['matches_frozen_v20']
assert hashlib.sha256((OUT/'baseline_v20_workflow.py').read_bytes()).hexdigest()==binding['expected_sha256']
spec=importlib.util.spec_from_file_location('src.content_factory.baseline_v20_workflow',OUT/'baseline_v20_workflow.py')
baseline=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=baseline
spec.loader.exec_module(baseline)
results={}
original=case._snapshot(case.REAL_RUN)
for label, runner in [('v20',baseline.CreativeWorkflow),('v21',CreativeWorkflow)]:
    instances=[]
    class TrackingClients(FakeClients):
        def __init__(self,answers):
            super().__init__(answers)
            instances.append(self)
    case.FakeClients=TrackingClients
    case.CreativeWorkflow=runner
    temp=OUT/('legacy_'+label)
    temp.mkdir()
    try:
        case.test_real_receipts_resume_offline_without_reset_or_invalidation(temp)
        error=None
    except Exception as exc:
        error=str(exc)
    state=json.loads((temp/'production_receipt_replay/state.json').read_text(encoding='utf-8'))
    results[label]={'error':error,'model_calls':sum(len(c.calls) for c in instances),
                    'calls_started':state['calls_started'],'status':state['status']}
results['matches_v20_failure']=results['v20']==results['v21']
results['historical_source_unchanged']=original==case._snapshot(case.REAL_RUN)
assert results['matches_v20_failure'] and results['historical_source_unchanged']
assert results['v21']['model_calls']==0
(OUT/'legacy_replay_comparison.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
