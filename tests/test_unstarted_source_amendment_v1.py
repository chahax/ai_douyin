from copy import deepcopy
import pytest
from test_natural_director_pipeline_v10 import auth,pipe
from src.content_factory.unstarted_source_amendment_v1 import amend,replace_json


@pytest.fixture
def pending(tmp_path,monkeypatch):
    registry=tmp_path/'registry'
    monkeypatch.setattr(pipe,'CANONICAL_REGISTRY',registry)
    monkeypatch.setattr(pipe.parent,'CANONICAL_REGISTRY',registry)
    monkeypatch.setattr(pipe.core,'_legacy_blocks',lambda *a,**k:[])
    source=tmp_path/'first.txt';source.write_text('第1章\n\n测试原文。'*30,encoding='utf-8')
    run=tmp_path/'writer'; authorization=auth(tmp_path,run,calls=6)
    pipe.prepare_source(run,authorization_path=authorization,source_path=source,title='测试书',book_id='1234567890123456789')
    next_file=tmp_path/'second.txt';next_file.write_text('第2章\n\n新增原文。'*30,encoding='utf-8')
    receipt=tmp_path/'acquisition.json'
    pipe.core._write(receipt,{'status':'source_saved','source':{'book_name':'测试书','book_id':'1234567890123456789','chapters':[{'path':str(source),'title':'第1章'},{'path':str(next_file),'title':'第2章'}]}})
    update=tmp_path/'update.json'
    pipe.core._write(update,{'run_dir':str(run.resolve()),'user_statement':'可以获取多个章节别就1章','external_text_services':['MiniMax','DeepSeek'],'max_text_calls':6})
    return run,receipt,update


def test_expansion_preserves_owner_budget_state_and_old_snapshot(pending):
    run,receipt,update=pending
    before=pipe.core._read(run/'BINDING.json'); original=(run/'BINDING.json').read_bytes()
    state=(run/'state.json').read_bytes()
    view=amend(run,receipt,before['brief'],update)
    after=pipe.core._read(run/'BINDING.json')
    assert view['status']=='prepared' and view['calls_started']==0
    assert after['source']['scope']['acquired_chapters']==2
    assert after['budget']==before['budget'] and after['run_dir']==before['run_dir']
    assert (run/'state.json').read_bytes()==state
    assert (run/'source_amendment_001/BINDING.json').read_bytes()==original
    for row in after['registry']:assert pipe.core._read(row['path'])['run_dir']==str(run.resolve())
    with pytest.raises(ValueError):amend(run,receipt,before['brief'],update)


@pytest.mark.parametrize('bad',['claimed','changed_book','changed_prefix'])
def test_refuses_unknown_or_different_story(pending,bad):
    run,receipt,update=pending
    before=pipe.core._read(run/'BINDING.json')
    if bad=='claimed':pipe.core._write(run/'CLAIM_001.json',{'unknown':True})
    elif bad=='changed_book':
        v=pipe.core._read(receipt);v['source']['book_id']='9999999999999999999';replace_json(receipt,v)
    else:
        v=pipe.core._read(receipt);v['source']['chapters'].reverse();replace_json(receipt,v)
    with pytest.raises((ValueError,RuntimeError)):
        amend(run,receipt,before['brief'],update)
    assert pipe.core._read(run/'BINDING.json')==before
