from pathlib import Path
import os,sys,socket,json
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'core_runtime.sqlite3').replace('\\','/')
os.environ['LLM_PROVIDER']='mock';os.environ['PYTHONIOENCODING']='utf-8'
def blocked(*args,**kwargs):raise RuntimeError('P1 verification prohibits networking')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
selected=['test_creative_workflow','test_creative_stage_debug','test_media_review_policy','test_media_user_review','test_task_queue_claim','test_llm_provider_contracts']
(OUT/'core_selection.json').write_text(json.dumps(selected,indent=2),encoding='utf-8')
import pytest
raise SystemExit(pytest.main(['tests/'+name+'.py' for name in selected]+['-q','-p','no:cacheprovider','--basetemp='+str(OUT/'core_tmp'),'--junitxml='+str(OUT/'core_tests.xml')]))
