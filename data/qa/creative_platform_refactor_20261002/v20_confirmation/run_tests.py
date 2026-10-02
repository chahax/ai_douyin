from pathlib import Path
import os,sys,socket,json
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
group=sys.argv[1]
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/(group+'_runtime.sqlite3')).replace('\\','/')
os.environ['LLM_PROVIDER']='mock';os.environ['PYTHONIOENCODING']='utf-8'
def blocked(*args,**kwargs):raise RuntimeError('Independent v20 verification prohibits network connections')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
selections={'core':['test_creative_workflow','test_creative_stage_debug','test_media_review_policy','test_media_user_review','test_task_queue_claim','test_llm_provider_contracts'],'governance':['test_creative_governance','test_creative_governed_protocol','test_creative_governed_rollback','test_migration_readiness']}
selected=selections[group]
(OUT/(group+'_selection.json')).write_text(json.dumps(selected,indent=2)+'\n',encoding='utf-8')
import pytest
raise SystemExit(pytest.main(['tests/'+name+'.py' for name in selected]+['-q','-p','no:cacheprovider','--basetemp='+str(OUT/(group+'_tmp')),'--junitxml='+str(OUT/(group+'_tests.xml'))]))

