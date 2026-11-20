import json
from scripts import run_xhigh_two_reviews_20261028 as m


def test_second_review_uses_revised_text_without_old_diagnosis(tmp_path, monkeypatch):
    parent = tmp_path/'parent'; parent.mkdir()
    run = tmp_path/'new'
    def put(name, value):
        (parent/name).write_text(json.dumps(value), encoding='utf-8')
    put('SOURCE.json', {'chapters':[{'index':1,'text':'完整原文'}]})
    put('PLAN.json', {'routes':{}})
    put('RESPONSE_001.json', {'native':{'choices':[{'message':{'tool_calls':[
        {'function':{'arguments':json.dumps({'analysis':'初稿','open_questions':[]})}}
    ]}}]}})
    seen=[]
    class FakeLedger:
        def __init__(self,*args): pass
        def save(self): pass
        def call(self,name,role,prompt,payload,schema):
            seen.append(payload)
            return {'analysis':'第一轮新稿' if len(seen)==1 else '第二轮新稿',
              'open_questions':[], 'corrections':[{'old_statement':'旧句',
              'revised_statement':'新句','chapter':1,'evidence':'完整原文'}]}
    monkeypatch.setattr(m,'PARENT',parent); monkeypatch.setattr(m,'RUN',run)
    monkeypatch.setattr(m,'Ledger',FakeLedger)
    m.execute()
    assert len(seen)==2
    assert seen[0]['current_analysis']=='初稿'
    assert seen[1]['current_analysis']=='第一轮新稿'
    assert 'corrections' not in seen[1]
    assert seen[1]['complete_chapters']==seen[0]['complete_chapters']
    assert '第二轮新稿' in (run/'ROUND_2_OUTPUT.md').read_text('utf-8')
    import pytest
    with pytest.raises(FileExistsError): m.execute()


def test_schema_requires_evidence_and_valid_chapter():
    from jsonschema import validate, ValidationError
    import pytest
    with pytest.raises(ValidationError):
        validate({'analysis':'a','open_questions':[], 'corrections':[
            {'old_statement':'a','revised_statement':'b','chapter':4,'evidence':'x'}]},m.SCHEMA)
