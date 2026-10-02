from pathlib import Path
import os,sys,socket
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'extended_test_runtime.sqlite3').replace('\\','/')
os.environ['LLM_PROVIDER']='mock'
def blocked(*args,**kwargs):raise RuntimeError('Independent v20 verification prohibits networking')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
import pytest
raise SystemExit(pytest.main([str(OUT/'test_extended_recovery.py'),'-q','-p','no:cacheprovider','--basetemp='+str(OUT/'extended_tmp'),'--junitxml='+str(OUT/'extended_tests.xml')]))



