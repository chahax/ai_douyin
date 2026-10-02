from pathlib import Path
import os,sys,socket,json
ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
mode=sys.argv[1]
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/(mode+'_runtime.sqlite3')).replace('\\','/')
os.environ['LLM_PROVIDER']='mock'
def blocked(*args,**kwargs):raise RuntimeError('Independent offline verification prohibits network connections')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
BASELINE=['test_workflow_nodes','test_account_runtime_binding','test_account_refresh_schedule','test_ai_content_declaration','test_publish_verification','test_publish_state_receipts','test_provider_call_ledger','test_seedance_client','test_creative_governance','test_creative_governed_protocol','test_creative_governed_rollback','test_video_campaign_script_budget','test_video_campaign_human_resume','test_creative_seedance_segments']
REFACTOR=['test_creative_workflow','test_creative_stage_debug','test_media_review_policy','test_media_user_review','test_script_video_run','test_script_video_ark','test_script_video_editorial_gate','test_script_video_review_packet','test_script_video_speed_preview','test_task_queue_claim','test_skill_outcome_unknown','test_publish_status_propagation','test_migration_readiness','test_llm_provider_contracts','test_creative_workflow_ui']
selected=BASELINE if mode=='baseline' else ['test_creative_workflow_ui'] if mode in ('ui','ui_long') else REFACTOR
(OUT/(mode+'_selected_tests.json')).write_text(json.dumps(selected,indent=2),encoding='utf-8')
if mode=='ui_long':
 from streamlit.testing.v1 import AppTest
 original=AppTest.from_string
 def with_long_timeout(*args,**kwargs):
  kwargs.setdefault('default_timeout',10)
  return original(*args,**kwargs)
 AppTest.from_string=staticmethod(with_long_timeout)
import pytest
raise SystemExit(pytest.main(['tests/'+name+'.py' for name in selected]+['-q','-p','no:cacheprovider','--basetemp='+str(OUT/(mode+'_tmp')),'--junitxml='+str(OUT/(mode+'_tests.xml'))]))
