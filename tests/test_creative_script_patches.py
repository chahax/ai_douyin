from copy import deepcopy
import pytest
from src.content_factory.creative_script_patches import apply_script_patches
from src.content_factory.creative_workflow_contract import CreativeContractError
from scripts.evaluate_minimax_script_events import evidence_errors


def test_patch_cannot_change_unapproved_fields_or_stale_text():
    source={"beats":[{"before":"拿壶","after":"放稳"}]};saved=deepcopy(source)
    patch={"patches":[{"path":"beats.0.before","before":"拿壶","after":"壶在台上"}]}
    assert apply_script_patches(source,patch,['beats.0.before'])['beats'][0]['after']=='放稳'
    assert source==saved
    with pytest.raises(CreativeContractError):apply_script_patches(source,patch,[])
    patch['patches'][0]['before']='旧版本'
    with pytest.raises(CreativeContractError):apply_script_patches(source,patch,['beats.0.before'])


def test_duplicate_path_and_invalid_review_evidence_rejected():
    edit={"path":"text","before":"a","after":"b"}
    with pytest.raises(CreativeContractError):apply_script_patches({'text':'a'},{'patches':[edit,edit]},['text'])
    samples=[{'sample_id':'X','script':{'beats':[{'before':'先开门'}]}}]
    review={'reviews':[{'sample_id':'X','issues':[{'severity':'major','evidence':[{'path':'beats.0.before','quote':'先关门'}]}]}]}
    assert evidence_errors(review,samples)
    review['reviews'][0]['issues'][0]['evidence'][0]['quote']='先开门'
    assert evidence_errors(review,samples)==[]


def test_adaptive_minimax_is_explicit_and_reasoning_stays_separate(monkeypatch):
    from types import SimpleNamespace
    import openai
    from src.content_factory import creative_workflow_roles as roles
    captured={}
    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content='{"ok":true}',tool_calls=[]))],model='MiniMax-M3',id='fake',usage=None)
    monkeypatch.setattr(openai,'OpenAI',lambda **kw:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(roles,'role_config',lambda role:roles.RoleConfig('minimax','MiniMax-M3','https://example.invalid','fake'))
    result=roles.CreativeRoleClients().call('writer',[],thinking='adaptive')
    assert captured['extra_body']=={'thinking':{'type':'adaptive'},'reasoning_split':True}
    assert result.text=='{"ok":true}'
    assert result.metadata['thinking_mode']=='adaptive'
    with pytest.raises(ValueError):roles.CreativeRoleClients().call('director',[],thinking='adaptive')
