import json
from pathlib import Path
import pytest
import scripts.run_fanqie_corpus_workflow as module

@pytest.mark.parametrize('terminal',['succeeded','outcome_unknown'])
def test_original_acquisition_drives_text_once_or_stops(tmp_path,monkeypatch,terminal):
    command={'command_id':'original','kind':'fanqie_book_inspect','state':terminal,'payload':{'book_name':'书','chapters':0}}
    class Accounts:
        db=tmp_path/'db';queued=0
        def queue(self,*a,**k):self.queued+=1;return command
        def folder(self,*a):return tmp_path/'evidence'
    class Store:
        def __init__(self,*a):pass
        def get(self,*a):return command
    monkeypatch.setattr(module,'BrowserControlStore',Store)
    a=Accounts();events=[]
    def launch(cmd,accounts):
        events.append('launch');module.atomic(a.folder()/'BOOK_INSPECTION.json',{'corpus':{'status':'accessible_catalogue_complete'},'corpus_path':str(tmp_path/'manifest')})
    def prepare(manifest,run,**kwargs):events.append('prepare');module.atomic(run/'STATE.json',{'status':'prepared'})
    def execute(run):events.append('execute');return {'status':'reviewed_draft_ready'}
    args=(tmp_path/'workflow','resource','书',tmp_path/'old','用户要求全量重跑')
    v=module.workflow(*args,execute_text=True,accounts=a,launch=launch,prepare_text=prepare,execute_script=execute)
    if terminal=='succeeded':
        assert events==['launch','prepare','execute'] and v['status']=='reviewed_draft_ready'
        module.workflow(*args,accounts=a,launch=launch,prepare_text=prepare)
        assert a.queued==1 and events.count('launch')==1 and events.count('prepare')==1
    else:assert events==['launch'] and v['state']=='outcome_unknown'


def test_workflow_default_prepare_reaches_new_review_revision_cycle(tmp_path,monkeypatch):
    from test_corpus_screenplay import setup_run
    from test_screenplay_revision_v4 import V4Client
    from src.content_factory.corpus_screenplay_v1 import execute
    setup_run(tmp_path/'source')
    command={'command_id':'original','kind':'fanqie_book_inspect','state':'succeeded','payload':{'book_name':'书','chapters':0}}
    class Accounts:
        db=tmp_path/'db'
        def queue(self,*a,**k):return command
        def folder(self,*a):return tmp_path/'evidence'
    class Store:
        def __init__(self,*a):pass
        def get(self,*a):return command
    monkeypatch.setattr(module,'BrowserControlStore',Store)
    accounts=Accounts();client=V4Client('revise')
    def launch(cmd,accounts):
        module.atomic(accounts.folder()/'BOOK_INSPECTION.json',{'corpus':{'status':'accessible_catalogue_complete'},
            'corpus_path':str(tmp_path/'source/m.json')})
    result=module.workflow(tmp_path/'workflow','resource','书',tmp_path/'source/old.json','测试完整流程',
        accounts=accounts,launch=launch,execute_text=True,execute_script=lambda run:execute(run,client),
        prepare_text=lambda *a,**k: module.prepare(*a,**k,parallel_analysis=False))
    assert result['status']=='reviewed_draft_ready' and client.writers==2 and client.reviews==4
    assert module.read(tmp_path/'workflow/text/PLAN.json')['review_cycle']['version']=='screenplay_revision/v4'
