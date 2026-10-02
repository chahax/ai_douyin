from pathlib import Path
import os,sys,socket
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'review_runtime.sqlite3').replace(chr(92),'/')
os.environ['LLM_PROVIDER']='mock'
def blocked(*args,**kwargs):raise RuntimeError('Independent v23 verification is offline')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
import pytest
code=pytest.main(['tests/test_creative_feedback_consistency.py',str(OUT/'fixed/test_inflight_feedback_contract.py'),'-q','--tb=short','-p','no:cacheprovider','--basetemp='+str(OUT/'boundary_tmp'),'--junitxml='+str(OUT/'boundary_tests.xml')])
raise SystemExit(code)
