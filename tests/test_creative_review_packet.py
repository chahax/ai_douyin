from copy import deepcopy
import json
from pathlib import Path
import pytest
from src.content_factory.creative_review_packet import (
    VERSION,REVIEW_SCHEMA,build_packet,build_prompt,validate_review,to_legacy_review,
    review_disposition,unknown_disposition,packet_diff,source_value,digest)
from src.content_factory.creative_workflow_contract import CreativeContractError
from src.content_factory.creative_review_gate import validate_review as validate_legacy


def context():
    return {'creative_brief':{'theme':'边界与尊重'},'script':{'beats':[
        {'id':'B01','before':'甲站立看乙','dialogue':[{'speaker':'C01','text':'我先回去。'}],'after':'乙点头'},
        {'id':'B02','before':'乙保持目光','dialogue':[],'after':'甲转向门口'}]},
        'state_plan':{'schema':'whole_film_action_plan_v2','initial_state':{'C01':{'posture':'standing','facing':'C02'}},
          'spatial_contract':{'seats':[{'seat_id':'E02','access_positions':['椅前侧'],'required_facing':'桌子'}]},
          'beats':[{'beat_id':'B01','camera':'两人中景','cut_reason':'说完再切','dialogue_performance':'说话时抬眼','groups':[{'id':'g1','performance':'甲站立看乙','operations':[{'kind':'gaze','actor':'C01','target':'C02','value':'C02'}]}]},
                   {'beat_id':'B02','camera':'保留反应','cut_reason':'点头后切','dialogue_performance':'无对白','groups':[]}]},
        'shots':{'style':{'scene':'办公室'},'shots':[
          {'id':'SH01','beat_id':'B01','start_state':'甲站立','end_state':'甲看乙','visible_performance':'说话时抬眼','camera':'两人中景','cut_reason':'说完再切','prompt':'甲站立说话时抬眼，镜头等待台词结束。'},
          {'id':'SH02','beat_id':'B02','start_state':'甲看乙','end_state':'甲看门口','visible_performance':'甲转向门口','camera':'两人中景','cut_reason':'转身后切','prompt':'甲看乙后转向门口。'}]},
        'scheduling_report':{'semantic_status':'not_checked','dialogue_seconds':2.3}}


def review(ctx):
    packet=build_packet(ctx)
    return {'schema':REVIEW_SCHEMA,'context_sha256':packet['context_sha256'],
            'checks':[{'check_id':c['check_id'],'status':'passed','reason':'测试模拟判断，仅验证协议','issue_ids':[],'unknown':None} for c in packet['checks']],
            'issues':[],'suggestions':[],'calibration_focus':[],'pending':[]}


def unknown(reason='SEMANTIC_AMBIGUITY'):
    return {'reason_code':reason,'missing_evidence':['椅前侧空间关系未明确'],'owner_stage':'action_plan','action':'补充证据后重新审核'}


def test_preserves_all_free_prose_and_spatial_sources_without_claiming_semantic_pass():
    ctx=context();packet=build_packet(ctx)
    assert packet_diff(ctx,packet)['semantic_coverage']==1
    for path in [('state_plan','beats','0','dialogue_performance'),('state_plan','beats','0','groups','0','performance'),('shots','shots','0','prompt'),('state_plan','spatial_contract','seats','0','access_positions','0')]:
        node=packet['source_map']
        for key in path:node=node[key]
        assert isinstance(source_value(packet,node),str)
    assert {r['kind'] for r in packet['comparisons']}=={'operations_vs_prose','end_vs_next_start','cut_vs_unfinished_tasks'}
    assert packet['automatic_approval'] is False
    assert 'dialogue_performance' in build_prompt(packet)


def test_complete_model_judgments_required_and_all_expanded_evidence_is_real():
    ctx=context();raw=review(ctx);original=deepcopy(raw)
    effective=to_legacy_review(raw,ctx);validate_legacy(effective,ctx)
    assert raw==original and effective['story_preserved'] is True
    assert review_disposition(raw,ctx)['automatic_approval'] is False
    raw['checks'].pop()
    with pytest.raises(CreativeContractError,match='explicitly covered'):to_legacy_review(raw,ctx)


def test_stale_context_missing_sources_and_tampered_packet_block():
    ctx=context();raw=review(ctx);ctx['shots']['shots'][0]['prompt']+='改动'
    with pytest.raises(CreativeContractError,match='stale'):validate_review(raw,ctx)
    ctx=context();del ctx['shots']['shots'][0]['camera']
    with pytest.raises(CreativeContractError,match='REQUIRED_EVIDENCE_MISSING'):build_packet(ctx)
    packet=build_packet(context());packet['sources']['E0001']='篡改'
    with pytest.raises(CreativeContractError,match='hash mismatch'):validate_review(review(context()),packet)


@pytest.mark.parametrize('reason,expected',[('SEMANTIC_AMBIGUITY','review_required'),('SOURCE_MISSING','blocked'),('EXPRESSION_UNSUPPORTED','blocked'),('OPTIONAL_AESTHETIC','review_required')])
def test_required_unknown_never_degrades_to_legacy_pass(reason,expected):
    ctx=context();raw=review(ctx);raw['checks'][0].update(status='unknown',unknown=unknown(reason))
    disposition=review_disposition(raw,ctx)
    assert disposition['disposition']==expected and disposition['can_handoff'] is False
    with pytest.raises(CreativeContractError,match='unknown blocks'):to_legacy_review(raw,ctx)


def test_advisory_pending_preserved_but_not_media_pass_or_current_semantic_escape():
    ctx=context();raw=review(ctx)
    raw['pending']=[dict(unknown('ACTUAL_MEDIA_AUDIO_PENDING'),scope='media')]
    assert review_disposition(raw,ctx)['disposition']=='advisory_pending'
    assert '非passed' in to_legacy_review(raw,ctx)['calibration_focus'][0]
    raw['pending']=[dict(unknown('SEMANTIC_AMBIGUITY'),scope='advisory')]
    with pytest.raises(CreativeContractError,match='cannot hide'):validate_review(raw,ctx)


def test_known_failure_requires_real_body_source_and_link_and_cannot_be_hidden():
    ctx=context();raw=review(ctx);packet=build_packet(ctx)
    sid=packet['source_map']['shots']['shots']['0']['visible_performance']
    raw['issues']=[{'id':'I1','owner':'director','location':'SH01','severity':'major','rule':'动作与文字一致','evidence':'说话时抬眼','contradiction':'模拟冲突','impact':'重复动作','proposal':'核对操作','evidence_ids':[sid]}]
    raw['checks'][2].update(status='failed',issue_ids=['I1'])
    assert review_disposition(raw,ctx)['disposition']=='failed'
    effective=to_legacy_review(raw,ctx);validate_legacy(effective,ctx)
    assert effective['story_preserved'] is False and effective['issues'][0]['evidence_refs']
    raw['checks'][2].update(status='unknown',unknown=unknown())
    with pytest.raises(CreativeContractError,match='cannot hide'):validate_review(raw,ctx)
    raw['checks'][2].update(status='failed',unknown=None)
    raw['issues'][0]['evidence_ids']=['invented']
    with pytest.raises(CreativeContractError,match='unknown evidence'):validate_review(raw,ctx)


def test_lossless_prompt_segment_reuse_keeps_unique_compiler_contradiction():
    ctx=context();long='甲看向乙，放下手中的文件夹，保持两秒等待回应。'*8
    ctx['state_plan']['beats'][0]['dialogue_performance']=long
    ctx['shots']['shots'][0]['prompt']=long+'但台词尚未说完即切走。'
    packet=build_packet(ctx);sid=packet['source_map']['shots']['shots']['0']['prompt']
    assert '$concat' in packet['sources'][sid]
    assert source_value(packet,sid)==ctx['shots']['shots'][0]['prompt']
    assert packet_diff(ctx,packet)['missing_semantic_paths']==[]


def test_historical_failed_request_is_preserved_and_measured_not_relabelled_passed():
    path=Path('data/production_trials/say_no_action_one_production_cycle_20260928/round_01/writer_check__state_plan_00.json')
    if not path.exists():pytest.skip('historical receipt not available')
    original=path.read_bytes();record=json.loads(original);ctx=json.loads(record['request']['messages'][1]['content'])
    packet=build_packet(ctx);diff=packet_diff(ctx,packet)
    assert diff['semantic_coverage']==1 and diff['missing_semantic_paths']==[]
    assert diff['packet_json_characters'] < diff['context_json_characters']
    assert path.read_bytes()==original
    assert not any('status' in row for row in packet['checks'])


def test_dictionary_order_does_not_change_source_ids_or_bound_packet():
    ctx=context();raw=review(ctx)
    def reorder(value):
        if isinstance(value,dict):return {k:reorder(v) for k,v in reversed(list(value.items()))}
        if isinstance(value,list):return [reorder(v) for v in value]
        return value
    changed=reorder(ctx)
    assert digest(ctx)==digest(changed)
    assert build_packet(ctx)==build_packet(changed)
    assert to_legacy_review(raw,ctx)==to_legacy_review(raw,changed)
