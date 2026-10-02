"""Offline production-entry acceptance; all provider/browser/media labels are fixtures."""
from pathlib import Path
import os, sys, socket, json
ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'acceptance_runtime.sqlite3').replace(chr(92),'/')
os.environ['LLM_PROVIDER']='mock'
os.environ['PYTHONIOENCODING']='utf-8'
def blocked(*args,**kwargs): raise RuntimeError('v22 offline acceptance prohibits network connections')
socket.socket.connect=blocked
socket.socket.connect_ex=blocked
import src.content_factory.creative_governed_runtime as governed
if len(sys.argv)>2:
    governed.REGISTRY_DIRECTORY=str((OUT/sys.argv[2]).relative_to(ROOT)).replace(chr(92),'/')
group=sys.argv[1]
prior=OUT.parent/'p1_closure_v21'
if group=='targeted': selected=['tests/test_creative_remaining_refactor.py','tests/test_creative_governed_protocol.py']
elif group=='changed_legacy': selected=['tests/test_creative_director_authority.py','tests/test_creative_review_gate.py','tests/test_creative_v4_integration.py','tests/test_creative_v5_integration.py']
elif group=='remaining_p1': selected=['tests/test_migration_readiness.py']
elif group=='p1': selected=json.loads((prior/'p1_selection.json').read_text(encoding='utf-8'))
else:
    selected=[str(p.relative_to(ROOT)).replace(chr(92),'/') for p in sorted((ROOT/'tests').glob('test_creative_*.py'))
              if p.name!='test_creative_real_receipt_replay.py']
    selected+=['tests/test_media_review_policy.py','tests/test_media_user_review.py',
               'tests/test_publish_verification.py','tests/test_publish_state_receipts.py',
               'tests/test_publish_status_propagation.py','tests/test_task_queue_claim.py',
               'tests/test_llm_provider_contracts.py']
    selected += [str(OUT.parent/'v20_confirmation'/name) for name in ('test_recovery_boundaries.py','test_extended_recovery.py')]
(OUT/(group+'_selection.json')).write_text(json.dumps(selected,indent=2),encoding='utf-8')
import pytest
class Tee:
    def __init__(self,stream,log):self.stream=stream;self.log=log
    def write(self,text):self.log.write(text);self.log.flush();return self.stream.write(text)
    def flush(self):self.log.flush();self.stream.flush()
    def isatty(self):return False
with (OUT/(group+'_tests.log')).open('w',encoding='utf-8') as log:
    sys.stdout=Tee(sys.stdout,log);sys.stderr=Tee(sys.stderr,log)
    code=pytest.main(selected+['-q','--tb=short','-p','no:cacheprovider',
        '--basetemp='+str(OUT/(group+'_tmp')),'--junitxml='+str(OUT/(group+'_tests.xml'))])
    print('ACCEPTANCE_EXIT_CODE='+str(code))
sys.stdout=sys.__stdout__;sys.stderr=sys.__stderr__
raise SystemExit(code)
