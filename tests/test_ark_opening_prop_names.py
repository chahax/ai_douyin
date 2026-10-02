"""Pure prop-name rendering and synthetic requests; no model or media approval."""
import copy
import json

import pytest

from scripts import run_script_video as runner
from src.content_factory import ark_opening_frame as opening
from src.content_factory.seedance_client import ARK_BASE_URL, ARK_MINI_MODEL, SeedanceConfig
from test_ark_opening_frame import MODEL, clients, sha
from test_reviewed_storyboard_direction import staged


START = ('甲在左、乙在右。P1（甲方合同）：桌左摊开；P2（乙方合同）：桌右摊开；'
         'P3（黑色签字笔）：甲的右手握着；P4（黑色手机）：桌右平放。')
PROMPT = '甲左乙右，P1、P2各一本；甲右手握P3，P4仍在桌右。\n只呈现这些道具。'
RENDERED = '甲左乙右，甲方合同、乙方合同各一本；甲右手握黑色签字笔，黑色手机仍在桌右。\n只呈现这些道具。'


def test_render_preserves_every_non_id_character_and_records_exact_source():
    rendered, recipe = opening.render_opening_prompt(PROMPT, START)
    assert rendered == RENDERED
    assert recipe == {'schema': 'opening_prop_names/v1', 'source_field': 'S01.start_frame',
                      'source_sha256': sha(START.encode()), 'input_prompt_sha256': sha(PROMPT.encode()),
                      'output_prompt_sha256': sha(RENDERED.encode()),
                      'prop_names': {'P1': '甲方合同', 'P2': '乙方合同', 'P3': '黑色签字笔', 'P4': '黑色手机'},
                      'replacements': {'P1': 1, 'P2': 1, 'P3': 1, 'P4': 1}}


def test_chinese_adjacent_ids_are_replaced_but_ascii_embedded_tokens_are_not():
    prompt = '左手握P3。P3在手中；P3/P3；AP3 P3A _P3 P3_ P30a p3 3P3。'
    rendered, recipe = opening.render_opening_prompt(prompt, START)
    assert rendered == ('左手握黑色签字笔。黑色签字笔在手中；黑色签字笔/黑色签字笔；'
                        'AP3 P3A _P3 P3_ P30a p3 3P3。')
    assert recipe['replacements'] == {'P3': 4}


@pytest.mark.parametrize('prompt', ['P5在桌面。', '只拍P30。', 'P01在左侧。'])
def test_undefined_independent_prop_id_is_rejected(prompt):
    with pytest.raises(ValueError):
        opening.render_opening_prompt(prompt, START)


@pytest.mark.parametrize('name', ['甲方合同', '另一份纸'])
def test_duplicate_source_definition_rejected_even_when_same_name(name):
    with pytest.raises(ValueError, match='[Dd]uplicate'):
        opening.render_opening_prompt('P1在桌左。', f'P1（甲方合同）：桌左；P1（{name}）：桌中。')


def test_no_ids_keeps_exact_text_and_empty_replacement_record():
    text = '两人相对而坐。\n\n  保持原始空白、光线与标点！'
    rendered, recipe = opening.render_opening_prompt(text, START)
    assert rendered == text and recipe['replacements'] == {}
    assert recipe['input_prompt_sha256'] == recipe['output_prompt_sha256']


@pytest.fixture
def prop_case(staged, tmp_path, monkeypatch):
    script, source, proof = staged
    script['shots'][0]['start_frame'] = START
    runner.write(source, script)
    proof['script_json_sha256'] = runner.sha(source)
    monkeypatch.setattr('src.trend_intelligence.saved_script_review.require_current_saved_script_review',
                        lambda path: copy.deepcopy(proof))
    config = SeedanceConfig(api_key='synthetic-key-only', base_url=ARK_BASE_URL,
                            model=ARK_MINI_MODEL, provider='ark_api')
    monkeypatch.setattr(SeedanceConfig, 'from_env', classmethod(lambda cls, *a, **kw: config))
    folder = tmp_path / 'run'
    manifest = runner.prepare(folder, source, 'Synthetic test only', provider='ark_api')
    plan = folder / 'opening_plan.json'
    runner.write(plan, {'schema': opening.PLAN_SCHEMA, 'shot_id': 'S01',
                       'script_sha256': manifest['script_sha256'],
                       'direction_sha256': manifest['direction_sha256'], 'prompt': PROMPT})
    attempt = folder / 'attempt_1'
    receipt = opening.prepare_opening_frame(folder, plan, attempt, config, model=MODEL, size='2K')
    return {'folder': folder, 'plan': plan, 'attempt': attempt, 'config': config, 'receipt': receipt}


def test_preparation_retains_original_plan_and_sends_only_mechanically_rendered_prompt(prop_case):
    case = prop_case
    request = runner.read(case['attempt'] / 'request.json')
    assert request['body']['prompt'] == RENDERED
    assert runner.read(case['plan'])['prompt'] == PROMPT
    assert (case['attempt'] / 'plan.original.json').read_bytes() == case['plan'].read_bytes()
    _, expected = opening.render_opening_prompt(PROMPT, START)
    assert case['receipt']['render_recipe'] == expected
    http, download, calls, _, _ = clients()
    with http, download:
        receipt = opening.submit_opening_frame(case['attempt'], case['config'],
                                               http_client=http, download_client=download)
    assert len(calls['post']) == 1
    assert json.loads(calls['post'][0].content)['prompt'] == RENDERED
    assert receipt['media_review'] == 'pending'


@pytest.mark.parametrize('field,value', [
    ('source_sha256', '0' * 64), ('output_prompt_sha256', '0' * 64),
    ('prop_names', {'P3': '红色笔'}), ('replacements', {'P3': 99}),
])
def test_recipe_tampering_is_rejected_before_post(prop_case, field, value):
    receipt = runner.read(prop_case['attempt'] / opening.RECEIPT_NAME)
    receipt['render_recipe'][field] = value
    runner.write(prop_case['attempt'] / opening.RECEIPT_NAME, receipt)
    http, download, calls, _, _ = clients()
    with http, download, pytest.raises(ValueError):
        opening.submit_opening_frame(prop_case['attempt'], prop_case['config'],
                                     http_client=http, download_client=download)
    assert calls == {'post': [], 'get': []}


def test_rehashed_modified_render_is_rejected_by_recipe_replay(prop_case):
    case = prop_case
    request = runner.read(case['attempt'] / 'request.json')
    request['body']['prompt'] = RENDERED.replace('黑色签字笔', '两支红色笔')
    runner.write(case['attempt'] / 'request.json', request)
    receipt = runner.read(case['attempt'] / opening.RECEIPT_NAME)
    receipt['request_sha256'] = runner.sha(case['attempt'] / 'request.json')
    receipt['render_recipe']['output_prompt_sha256'] = sha(request['body']['prompt'].encode())
    receipt['render_recipe']['prop_names']['P3'] = '两支红色笔'
    runner.write(case['attempt'] / opening.RECEIPT_NAME, receipt)
    http, download, calls, _, _ = clients()
    with http, download, pytest.raises(ValueError):
        opening.submit_opening_frame(case['attempt'], case['config'], http_client=http, download_client=download)
    assert calls == {'post': [], 'get': []}


def test_old_receipt_without_recipe_uses_exact_raw_prompt_and_plan_reservation(prop_case):
    case = prop_case
    request = runner.read(case['attempt'] / 'request.json')
    request['body']['prompt'] = PROMPT
    runner.write(case['attempt'] / 'request.json', request)
    receipt = runner.read(case['attempt'] / opening.RECEIPT_NAME)
    receipt.pop('render_recipe')
    receipt['request_sha256'] = runner.sha(case['attempt'] / 'request.json')
    runner.write(case['attempt'] / opening.RECEIPT_NAME, receipt)
    http, download, calls, _, _ = clients()
    with http, download:
        result = opening.submit_opening_frame(case['attempt'], case['config'],
                                              http_client=http, download_client=download)
    assert json.loads(calls['post'][0].content)['prompt'] == PROMPT
    assert result['reservation_path'].endswith(result['plan_sha256'] + '.json')
    assert 'render_recipe' not in result


def test_recipe_cannot_be_removed_while_keeping_rendered_request(prop_case):
    receipt = runner.read(prop_case['attempt'] / opening.RECEIPT_NAME)
    receipt.pop('render_recipe')
    runner.write(prop_case['attempt'] / opening.RECEIPT_NAME, receipt)
    http, download, calls, _, _ = clients()
    with http, download, pytest.raises(ValueError):
        opening.submit_opening_frame(prop_case['attempt'], prop_case['config'],
                                     http_client=http, download_client=download)
    assert calls == {'post': [], 'get': []}


def test_same_plan_cannot_submit_again_even_if_request_size_changes(prop_case):
    case = prop_case
    http, download, calls, _, _ = clients()
    with http, download:
        first = opening.submit_opening_frame(case['attempt'], case['config'],
                                             http_client=http, download_client=download)
        second_dir = case['folder'] / 'attempt_2'
        second = opening.prepare_opening_frame(case['folder'], case['plan'], second_dir,
                                               case['config'], model=MODEL, size='4K')
        assert second['request_sha256'] != first['request_sha256']
        assert first['plan_sha256'] == second['plan_sha256']
        with pytest.raises(FileExistsError):
            opening.submit_opening_frame(second_dir, case['config'], http_client=http, download_client=download)
    assert len(calls['post']) == 1

