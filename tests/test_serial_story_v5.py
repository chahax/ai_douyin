import json
from pathlib import Path
import pytest
from jsonschema import ValidationError
from test_serial_story_v1 import make_run,source
from test_serial_story_v3 import FakeV3,valid_material
from src.content_factory import serial_story_production_v5 as p
from src.content_factory import serial_story_contract_v5 as c
from src.content_factory.corpus_screenplay_v1 import read,digest


def test_material_review_cannot_request_episode_repair():
    material=valid_material()
    review={'candidate_sha256':digest(material),'decision':'revise','rationale':'test',
            'issues':[{'owner':'episode','path':'/claims/0','reason':'test','source_ids':['CH1-P001']}]}
    with pytest.raises(ValidationError): c.review_valid_for_stage(review,material,source(),'MATERIAL_REVIEW_0001')
    review['issues'][0]['owner']='materials'
    c.review_valid_for_stage(review,material,source(),'MATERIAL_REVIEW_0001')


def test_real_v4_misrouted_review_rejected_before_adjudication():
    root=Path('data/corpus_production_trials/20261027_serial_novel_v4_production')
    if not (root/'RESPONSE_003.json').exists(): pytest.skip('private native receipt unavailable')
    def value(n): return json.loads(read(root/f'RESPONSE_{n:03}.json')['native']['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    with pytest.raises(ValidationError): c.review_valid_for_stage(value(3),value(2),read(root/'SOURCE.json'),'MATERIAL_REVIEW_0001')


def test_v5_full_simulated_chain(tmp_path):
    make_run(tmp_path); run=tmp_path/'v5'
    p.prepare(tmp_path/'manifest.json',run,user_statement='offline')
    result=p.execute(run,fixture_client=FakeV3())
    assert result['error'] is None,result


def test_partial_adjudication_only_passes_verified_issue_to_repair(tmp_path):
    from test_serial_story_v2 import native_value,set_value
    class Partial(FakeV3):
        issued=False
        def call(self,role,messages,schema):
            payload=json.loads(messages[1]['content'])
            native=super().call(role,messages,schema); value=native_value(native)
            if 'review_sha256' in payload:
                issue={**payload['review']['issues'][0],'reason':'只修已证实的范围'}
                value={'candidate_sha256':payload['candidate_sha256'],'review_sha256':payload['review_sha256'],
                       'findings':[{'index':0,'verdict':'upheld','reason':'原判断一部分不成立','source_ids':['CH1-P001'],'validated_issue':issue}]}
            elif 'candidate' in payload and 'chapter_index' in payload['candidate'] and not self.issued:
                value.update(decision='revise',issues=[{'owner':'materials','path':'/claims/0/statement','reason':'混合错误意见','source_ids':['CH1-P001']}]);self.issued=True
            elif 'chapter' in payload and 'required_corrections' in payload:
                assert payload['required_corrections']['issues'][0]['reason']=='只修已证实的范围'
                assert '不能执行裁决驳回' in messages[0]['content']
                value['claims'][0]['statement']='经证据确认的交接'
            return set_value(native,value)
    make_run(tmp_path); run=tmp_path/'v5repair'; p.prepare(tmp_path/'manifest.json',run,user_statement='offline')
    result=p.execute(run,fixture_client=Partial())
    assert result['error'] is None,result


def test_rejected_adjudication_cannot_smuggle_repair():
    from src.content_factory.serial_story_runtime_v5 import adjudication_valid
    candidate=valid_material(); issue={'owner':'materials','path':'/claims/0','reason':'test','source_ids':['CH1-P001']}
    review={'candidate_sha256':digest(candidate),'decision':'revise','issues':[issue],'rationale':'test'}
    raw={'candidate_sha256':digest(candidate),'review_sha256':digest(review),'findings':[
        {'index':0,'verdict':'rejected','reason':'错误意见','source_ids':['CH1-P001'],'validated_issue':issue}]}
    with pytest.raises(ValueError,match='must_not_drive_repair'): adjudication_valid(raw,candidate,review,source())
