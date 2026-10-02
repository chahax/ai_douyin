import json
from copy import deepcopy
from pathlib import Path
import pytest
from src.content_factory.creative_segmented_director import (
    AUTHORITATIVE_VERSION, bind_segmented_director, generate_reviewed_beats,
    project_previous_execution, compile_execution_storyboard, validate_execution_contract,
)
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_segmented_director import Harness


def new_harness(tmp_path, decisions):
    w = Harness(decisions, tmp_path)
    w.state['segmented_director_binding'] = bind_segmented_director(authoritative=True)
    for s in w.answers[3]['shots']:
        s['production_choices'] = []
    return w


def test_old_binding_retains_old_payload_and_output(tmp_path):
    w = Harness([[], []], tmp_path)
    result = generate_reviewed_beats(w, w.answers[2], w.answers[1], {})
    assert w.seen[2][1]['previous_shot'] == result['shots'][0]
    assert result['shots'][0]['prompt'] == w.answers[3]['shots'][0]['prompt']
    assert not list(tmp_path.glob('*effective_execution.json'))


def test_authority_carries_only_reached_state_and_compiles_reviewed_prompt(tmp_path):
    w = new_harness(tmp_path, [[], []])
    raw = deepcopy(w.answers[3])
    raw['shots'][0]['cut_reason'] = '下一镜乙抬头（故意错误的未来预测）'
    w.answers[3] = raw
    result = generate_reviewed_beats(w, w.answers[2], w.answers[1], {})
    carried = w.seen[2][1]['previous_shot']
    assert set(carried) == {'id', 'beat_id', 'end_state'}
    assert carried['end_state'] == raw['shots'][0]['end_state']
    assert '故意错误' not in json.dumps(carried, ensure_ascii=False)
    assert result['shots'][0]['prompt'] != raw['shots'][0]['prompt']
    assert raw['shots'][0]['visible_performance'] in result['shots'][0]['prompt']
    assert w.seen[1][1]['shots']['shots'][0]['prompt'] == result['shots'][0]['prompt']
    assert w.answers[3] == raw
    assert len(list(tmp_path.glob('*effective_execution.json'))) == 2


def test_effective_replay_is_stable_and_tampering_not_overwritten(tmp_path):
    w = new_harness(tmp_path, [None])
    generate_reviewed_beats(w, w.answers[2], w.answers[1], {})
    w2 = new_harness(tmp_path, [None])
    generate_reviewed_beats(w2, w2.answers[2], w2.answers[1], {})
    assert w.seen == w2.seen
    path = next(tmp_path.glob('*effective_execution.json'))
    path.write_text('{}', encoding='utf-8')
    w3 = new_harness(tmp_path, [None])
    with pytest.raises(CreativeContractError, match='不能覆盖历史'):
        generate_reviewed_beats(w3, w3.answers[2], w3.answers[1], {})


def test_real_failed_sh04_duplicate_instructions_and_hidden_cut_rejected():
    fixture = json.loads((Path(__file__).parent / 'fixtures/director_sh04_conflict_20260927.json').read_text(encoding='utf-8'))
    value = {'shots': [deepcopy(fixture['shot'])]}
    with pytest.raises(CreativeContractError, match='production_choices'):
        validate_execution_contract(value)
    value['shots'][0]['production_choices'] = []
    with pytest.raises(CreativeContractError, match='镜内切镜'):
        validate_execution_contract(value)


def test_prohibition_of_cut_does_not_trigger_gate():
    validate_execution_contract({'shots':[{'id':'SH01','camera':'固定机位，无硬切。',
        'visible_performance':'人物逐渐抬头，不切到第二机位。','production_choices':[]}]})
