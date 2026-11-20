import json
from pathlib import Path
import pytest
from test_serial_story_v3 import valid_material,FakeV3
from test_serial_story_v1 import chapter,make_run
from src.content_factory import serial_story_contract_v4 as c
from src.content_factory import serial_story_production_v4 as p
from src.content_factory.corpus_screenplay_v1 import read


def test_integer_chapter_contract_and_precise_repair_feedback():
    schema=c.material_schema(chapter(1))
    assert schema['properties']['chapter_index']=={'type':'integer','const':1}
    value=valid_material(); value['chapter_index']='1'
    with pytest.raises(c.ContractErrors) as err: c.material_valid(value,chapter(1))
    errors=err.value.errors
    assert any(e['rule']=='type' and e['actual']=='1' and e['expected']=='integer' for e in errors)
    assert any(e['rule']=='const' and e['actual']=='1' and e['expected']==1 for e in errors)
    assert value['chapter_index']=='1'


def test_actual_v3_receipt_has_only_chapter_type_failure():
    root=Path('data/corpus_production_trials/20261027_serial_novel_v3_production')
    if not (root/'RESPONSE_002.json').exists(): pytest.skip('private native receipt unavailable')
    n=read(root/'RESPONSE_002.json')['native']
    value=json.loads(n['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    with pytest.raises(c.ContractErrors) as error: c.material_valid(value,read(root/'SOURCE.json')['chapters'][0])
    assert all(e['path']=='/chapter_index' for e in error.value.errors)


def test_full_v4_two_episode_simulation(tmp_path):
    make_run(tmp_path); run=tmp_path/'v4'
    p.prepare(tmp_path/'manifest.json',run,user_statement='offline only')
    result=p.execute(run,fixture_client=FakeV3())
    assert result['error'] is None,result
    assert result['accepted_episodes']==2
