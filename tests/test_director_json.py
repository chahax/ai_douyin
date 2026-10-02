import json
import pytest
from src.content_factory.director_json import terminal_delimiter, repair_failed_output, authored_value


@pytest.mark.parametrize('raw', ['{"beats":[{"text":"不要改动我"}]]', '{"beats":[{"text":"不要改动我"}]'])
def test_final_delimiter_only_preserves_content(raw):
    value, repair = terminal_delimiter(raw)
    assert value == {'beats': [{'text': '不要改动我'}]}
    assert repair['new'] == '}'
    assert repair['recipe'] == 'terminal_container_delimiter/v1'


@pytest.mark.parametrize('raw', [
    '{"text":"没说完', '{"beats":[{"text":"未闭合"',
    '{"a":1 "b":2}', '{"a":1,}', '{"a":[1},"b":2}',
    '{"a":1,"a":2}', '{"a":NaN}', '{"a":1} trailing',
])
def test_interior_ambiguous_or_incomplete_content_is_rejected(raw):
    with pytest.raises(ValueError):
        terminal_delimiter(raw)


def test_quotes_and_brackets_inside_strings_are_unchanged():
    raw = '{"text":"他说\\\"[别走]\\\"", "n":2] \n'
    value, _ = terminal_delimiter(raw)
    assert value == {'text': '他说"[别走]"', 'n': 2}


def make_failed(folder, finish='stop'):
    (folder/'raw.txt').write_text('{"beats":[]]', encoding='utf-8')
    (folder/'response.json').write_text(json.dumps({'finish_reason': finish}), encoding='utf-8')


def test_repair_is_replayable_without_changing_raw(tmp_path):
    make_failed(tmp_path)
    original = (tmp_path/'raw.txt').read_bytes()
    expected = repair_failed_output(tmp_path)
    assert authored_value(tmp_path) == expected == {'beats': []}
    assert (tmp_path/'raw.txt').read_bytes() == original
    assert not (tmp_path/'review.json').exists()
    assert not (tmp_path/'validation.json').exists()
    with pytest.raises(ValueError, match='existing'):
        repair_failed_output(tmp_path)
    (tmp_path/'raw.txt').write_text('{"beats":[1]]', encoding='utf-8')
    with pytest.raises(ValueError, match='provenance'):
        authored_value(tmp_path)


def test_length_truncated_response_is_never_repaired(tmp_path):
    make_failed(tmp_path, 'length')
    with pytest.raises(ValueError, match='non-truncated'):
        repair_failed_output(tmp_path)
    assert not (tmp_path/'candidate.json').exists()


def test_syntax_repair_does_not_make_a_semantic_approval(tmp_path):
    from scripts.run_reference_director import approved
    make_failed(tmp_path)
    repair_failed_output(tmp_path)
    with pytest.raises(FileNotFoundError):
        approved(tmp_path)
