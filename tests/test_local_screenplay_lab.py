from scripts.local_screenplay_lab import allocate,measure,invoke,write
import pytest


def plan():
    return {'beats':[{'event':'交接','place':'家中','parallel_action':'目光跟随','end_state':'钥匙由对方持有',
        'dialogue':[{'speaker':'甲','line':'钥匙交给你。'}], 'serial_seconds':2} for _ in range(3)]}


def test_budget_tracks_dialogue_and_is_contiguous():
    p=plan();p['beats'][1]['dialogue'][0]['line']*=4
    result=allocate(p)
    assert sum(b['duration_seconds'] for b in result)==90
    assert result[1]['duration_seconds']>result[0]['duration_seconds']
    assert result[0]['range'].startswith('0—') and result[-1]['range'].endswith('—90')


def test_oversized_plan_is_not_silently_compressed():
    p=plan()
    for beat in p['beats']:beat['dialogue'][0]['line']*=100
    with pytest.raises(ValueError,match='overflow'):allocate(p)


def test_format_failure_and_overflow_are_separate():
    assert not measure('无时间段')['format_valid']
    assert measure('### 【0—1秒】\n甲：“一句根本念不完的长句。”')['blocking_issues']
    result=measure('### 【0—1秒】\n甲：“一句根本念不完的长句。”\n### 【2—5秒】\n甲：“好了。”')
    assert not result['format_valid'] and len(result['blocking_issues'])==1


def test_pending_local_request_never_replays(tmp_path):
    write(tmp_path/'REQUEST.json',{'old':'request'})
    with pytest.raises(ValueError,match='requires_original_result'):
        invoke(tmp_path,'http://127.0.0.1:1','local',[])


def test_remote_endpoint_cannot_receive_novel_source(tmp_path):
    with pytest.raises(ValueError,match='loopback'):
        invoke(tmp_path,'https://example.com','local',[{'role':'user','content':'source'}])
    assert not (tmp_path/'REQUEST.json').exists()


def test_completed_response_cannot_be_relabelled_for_other_input(tmp_path):
    from scripts.local_screenplay_lab import sha
    write(tmp_path/'REQUEST.json',{'base':'http://127.0.0.1:1','body':{'model':'old'},'messages_sha256':sha([])})
    write(tmp_path/'RESPONSE.json',{'done':True,'done_reason':'stop','message':{'content':'old output'}})
    with pytest.raises(ValueError,match='input_changed'):invoke(tmp_path,'http://127.0.0.1:1','new',[])


def test_unquoted_real_output_cannot_be_reported_as_zero_speech_pass():
    result=measure('### 【0—15 秒】\n环境：办公室。\n苏墨：（平静）老师，今天我给了他二十块。')
    assert result['format_valid']
    assert not result['speech_measurement_usable']
    assert len(result['dialogue_format_suspects'])==1
    assert not result['quality_pass']


def test_mixed_quoted_and_unquoted_dialogue_remains_uncertain():
    result=measure('### 【0—15秒】\n甲：“我没偷。”\n苏墨：先查清楚。')
    assert result['segments'][0]['spoken_units']>0
    assert not result['speech_measurement_usable']


def test_cached_result_cannot_be_relabelled_with_different_thinking(tmp_path):
    from scripts.local_screenplay_lab import sha
    write(tmp_path/'REQUEST.json',{'base':'http://127.0.0.1:1','messages_sha256':sha([]),
        'body':{'model':'qwen3.5:9b','think':False,'options':{'num_predict':6144}}})
    write(tmp_path/'RESPONSE.json',{'done':True,'done_reason':'stop','message':{'content':'old output'}})
    with pytest.raises(ValueError,match='parameters_changed'):
        invoke(tmp_path,'http://127.0.0.1:1','qwen3.5:9b',[],thinking=True)
