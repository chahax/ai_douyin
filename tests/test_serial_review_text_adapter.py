import pytest
from scripts.produce_serial_prose import SerialLedger,decode_markdown_episode,map_complete_native_prose
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger
from src.content_factory.corpus_screenplay_v1 import freeze,read

@pytest.mark.parametrize('name,pending,finish,accept',[
    ('AUDIT_01',None,'stop',True),
    ('AUDIT_01',3,'stop',False),('AUDIT_01',None,'length',False)])
def test_only_known_complete_advisory_text_is_mapped(tmp_path,monkeypatch,name,pending,finish,accept):
    native={'choices':[{'finish_reason':finish,'message':{'content':'原始审核\n不作通过承诺。','tool_calls':[]}}]}
    freeze(tmp_path/'RESPONSE_003.json',{'native':native})
    def fail(*args,**kwargs):raise RuntimeError('native_tool_submission_missing')
    monkeypatch.setattr(DirectLedger,'call',fail)
    ledger=SerialLedger(tmp_path,{}, {'calls_started':3,'pending':pending},None)
    if accept:
        assert ledger.call(name,'writer','',{}, {})=={'review':native['choices'][0]['message']['content']}
        assert read(tmp_path/(name+'_TEXT_ADAPTER.json'))['semantic_acceptance'] is False
    else:
        with pytest.raises((RuntimeError,ValueError)):ledger.call(name,'writer','',{}, {})
        assert not (tmp_path/(name+'_TEXT_ADAPTER.json')).exists()

def test_marked_prose_extraction_preserves_every_character():
    content='## 第1集 标题\n\n原生正文。\n\n**continuity**：\n原生承接。\n'
    value=decode_markdown_episode(content)
    assert value['screenplay']+'**continuity**：'+value['continuity']==content
    assert value['title']=='第1集 标题'

@pytest.mark.parametrize('text',['正文没有标记','正文**continuity**：',
    '正文**continuity**：承接**continuity**：重复'])
def test_ambiguous_or_incomplete_prose_does_not_pass(text):
    with pytest.raises(ValueError):decode_markdown_episode(text)

def test_unstructured_known_prose_is_preserved_with_explicit_missing_state():
    text='# 原始标题\n\n完整原生正文，不含连续性字段。'
    mapped=map_complete_native_prose(text,'目录标题')
    assert mapped['screenplay']==text
    assert mapped['title']=='目录标题'
    assert mapped['continuity'].startswith('[程序记录：')
    assert '不能据此推断' in mapped['continuity']
