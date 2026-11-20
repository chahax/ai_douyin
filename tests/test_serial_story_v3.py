import json
from copy import deepcopy
from pathlib import Path
import pytest
from jsonschema import validate,ValidationError
from test_serial_story_v1 import chapter,material,Fake,make_run
from src.content_factory import serial_story_contract_v3 as c
from src.content_factory import serial_story_production_v3 as p
from src.content_factory.corpus_screenplay_v1 import read,digest


def valid_material():
    value=material(1)
    value['coverage']=[{'source_id':'CH1-P001','status':'covered','claim_ids':['F1']}]
    return value


@pytest.mark.parametrize('status',['covered','omitted'])
def test_schema_and_validator_agree_on_alternatives(status):
    value=valid_material()
    if status=='omitted': value['coverage']=[{'source_id':'CH1-P001','status':'omitted','reason':'非本次材料，供语义审核判断'}]
    validate(value,c.material_schema(chapter(1))); c.material_valid(value,chapter(1))


@pytest.mark.parametrize('mutation',['old_reason','missing_status','omitted_claims','blank_reason','empty_claims'])
def test_ambiguous_coverage_rejected_by_both_layers(mutation):
    value=valid_material(); row=value['coverage'][0]
    if mutation=='old_reason': row['omission_reason']='已经覆盖'
    elif mutation=='missing_status': row.pop('status')
    elif mutation=='empty_claims': row['claim_ids']=[]
    elif mutation=='omitted_claims': row.update(status='omitted',reason='说明')
    else: value['coverage']=[{'source_id':'CH1-P001','status':'omitted','reason':'  '}]
    with pytest.raises(ValidationError): validate(value,c.material_schema(chapter(1)))
    with pytest.raises(c.ContractErrors): c.material_valid(value,chapter(1))


def test_real_failed_receipt_reports_all_five_invalid_edges_without_editing():
    root=Path('data/corpus_production_trials/20261027_serial_novel_v2_prepared')
    if not (root/'RESPONSE_002.json').exists(): pytest.skip('private original production evidence unavailable')
    native=read(root/'RESPONSE_002.json')['native']
    value=json.loads(native['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    before=digest(value); ch=read(root/'SOURCE.json')['chapters'][0]
    with pytest.raises(c.ContractErrors) as error: c.material_valid(value,ch)
    errors=error.value.errors
    assert len([e for e in errors if e['code']=='coverage_without_evidence'])==5
    assert all('path' in e for e in errors)
    assert digest(value)==before


class FakeV3(Fake):
    def call(self,role,messages,schema):
        native=super().call(role,messages,schema)
        payload=json.loads(messages[1]['content'])
        if 'chapter' in payload:
            args=native['choices'][0]['message']['tool_calls'][0]['function']
            value=json.loads(args['arguments'])
            for row in value['coverage']:
                row.pop('omission_reason'); row['status']='covered'
            args['arguments']=json.dumps(value,ensure_ascii=False)
            assert payload['material_contract_rules']==c.COVERAGE_RULES
            assert all(rule in messages[0]['content'] for rule in c.COVERAGE_RULES.values())
        return native


def test_new_contract_full_two_episode_simulation(tmp_path):
    make_run(tmp_path)
    run=tmp_path/'v3'; p.prepare(tmp_path/'manifest.json',run,user_statement='offline only')
    result=p.execute(run,fixture_client=FakeV3())
    assert result['error'] is None,result
    assert result['accepted_episodes']==2 and result['simulation']


def test_multiple_bad_edges_are_reported_together():
    ch=chapter(1); ch['text']='林岚。\n阿禾。'
    value={'chapter_index':1,'claims':[{'id':'F','category':'character','statement':'林岚','evidence':[{'source_id':'CH1-P001','quote':'林岚'}]}],
           'coverage':[{'source_id':'CH1-P001','status':'covered','claim_ids':['missing']},
                       {'source_id':'CH1-P002','status':'covered','claim_ids':['F']}]}
    with pytest.raises(c.ContractErrors) as err: c.material_valid(value,ch)
    assert {e['code'] for e in err.value.errors}=={'claim_missing','coverage_without_evidence'}


def test_continuation_cannot_reset_or_duplicate_budget(tmp_path):
    from src.platform_adapter.fanqie_book_corpus import atomic
    from src.content_factory.corpus_screenplay_v1 import freeze
    parent=make_run(tmp_path); plan=read(parent/'PLAN.json')
    freeze(parent/'AUTHORIZATION.json',{'plan_sha256':digest(plan),'origin':'explicit_user_approval'})
    state=read(parent/'STATE.json'); state.update(status='needs_attention',calls_started=2,reported_tokens=40)
    atomic(parent/'STATE.json',state)
    with pytest.raises(ValueError,match='remaining'):
        p.prepare(tmp_path/'manifest.json',tmp_path/'bad',user_statement='continue',max_calls=400,parent_run=parent)
    assert not (parent/'BUDGET_TRANSFER.json').exists()
    child=p.prepare(tmp_path/'manifest.json',tmp_path/'child',user_statement='continue',max_calls=398,parent_run=parent)
    assert child['max_calls']+child['parent']['consumed_calls']==400
    with pytest.raises(ValueError,match='already_transferred'):
        p.prepare(tmp_path/'manifest.json',tmp_path/'duplicate',user_statement='continue',max_calls=398,parent_run=parent)
