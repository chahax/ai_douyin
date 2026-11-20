import pytest
from scripts.run_story_holdout import prepare
from src.content_factory.corpus_screenplay_v1 import freeze,read

def fixture(tmp_path,pending=None):
    prior=tmp_path/'prior';prior.mkdir()
    freeze(prior/'STATE.json',{'status':'needs_attention','pending':pending,'calls_started':141,
       'reported_tokens':100,'retained_unknowns':[{'call':135,'usage':None}],'reported_usage_complete':False})
    freeze(prior/'PLAN.json',{'max_calls':142})
    source=tmp_path/'source.json'
    freeze(source,{'chapters':[{'index':i,'text':str(i)} for i in range(1,14)]})
    return prior,source

def test_holdout_excludes_future_and_never_imports_reviewed_answers(tmp_path):
    prior,source=fixture(tmp_path);run=tmp_path/'run'
    prepare(run,prior,source,12,147)
    assert len(read(run/'SOURCE.json')['chapters'])==12
    assert len(read(source)['chapters'])==13
    assert read(run/'PACKET.json')['entities']==[]
    assert read(run/'CONFIG.json')['use_reviewed_materials'] is False
    state=read(run/'STATE.json')
    assert state['calls_started']==141 and state['retained_unknowns'][0]['call']==135
    assert state['reported_usage_complete'] is False
    assert read(prior/'PLAN.json')['max_calls']==142

def test_unsettled_predecessor_cannot_be_replayed(tmp_path):
    prior,source=fixture(tmp_path,142)
    with pytest.raises(ValueError,match='unsettled'):prepare(tmp_path/'run',prior,source,12,147)
    assert not (tmp_path/'run').exists()

def test_context_window_preserves_complete_chapters(tmp_path):
    prior,source=fixture(tmp_path);run=tmp_path/'window'
    prepare(run,prior,source,13,147,11)
    selected=read(run/'SOURCE.json')['chapters']
    assert selected==read(source)['chapters'][10:13]
    assert read(run/'EVALUATION_PLAN.json')['context_start']==11
