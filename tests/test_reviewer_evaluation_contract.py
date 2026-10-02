from copy import deepcopy
import pytest
from scripts.reviewer_evaluation_contract import inspect_review

SAMPLES=[{'sample_id':'S1','brief':{'constraints':['不超过10秒']},'script':{'beats':[{'duration_seconds':10,'before':'站在桌旁。','dialogue':[{'speaker':'甲','text':'你好。'}]}]}}]
def response(path='beats.0.before',quote='站在桌旁'):
    return {'reviews':[{'sample_id':'S1','strength':'动作清晰','issues':[{'severity':'major','category':'timing','evidence':[{'path':path,'quote':quote}],'impact':'具体影响','proposal':'具体修复目标'}]}]}
@pytest.mark.parametrize('path,quote',[('beats.0.before','站在桌旁'),('brief.constraints.0','不超过10秒'),('beats.0.duration_seconds','10'),('script.beats.0.dialogue.0.text','你好。')])
def test_literal_scalar_citation(path,quote):
    result=inspect_review(response(path,quote),SAMPLES)
    assert result['errors']==[]
    assert result['automatic_approval'] is False
@pytest.mark.parametrize('path,quote',[('beats.0.dialogue','你好。'),('beats.0.before','不存在'),('beats.8.before','站在桌旁'),('beats.-1.before','站在桌旁'),('beats.0.duration_seconds','1')])
def test_bad_citation(path,quote):
    assert inspect_review(response(path,quote),SAMPLES)['errors']
def test_missing_issues_is_not_clean():
    r=response();del r['reviews'][0]['issues']
    assert any(x['path'].endswith('.issues') for x in inspect_review(r,SAMPLES)['errors'])
def test_missing_proposal_and_duplicate_sample():
    r=response();del r['reviews'][0]['issues'][0]['proposal'];r['reviews'].append(deepcopy(r['reviews'][0]))
    errors=inspect_review(r,SAMPLES)['errors']
    assert any(x['kind']=='sample_coverage' for x in errors)
    assert any(x['path'].endswith('.proposal') for x in errors)
@pytest.mark.parametrize('bad',[None,[],{}, {'reviews':None},{'reviews':[None]}, {'reviews':[{'sample_id':{},'issues':None}]}])
def test_malformed_response_does_not_pass(bad):
    assert inspect_review(bad,SAMPLES)['errors']
