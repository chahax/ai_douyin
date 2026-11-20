from copy import deepcopy
from pathlib import Path
import pytest

from test_narration_placement_policy_v2 import cli,candidate,receipt
from src.content_factory import narration_source_case_adapter_v1 as a
from src.content_factory import narration_placement_policy_v2 as p

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'data/video_generation/h3_library_bound_next_minute_20261113_v1'


def inputs(tmp_path,modify=None):
    case=cli.case_v2();c=candidate(case)
    if modify:modify(c)
    r=receipt(case,c)
    p.freeze(tmp_path/'CASE.json',case);p.freeze(tmp_path/'RECEIPT.json',r)
    return p.bind(tmp_path/'CASE.json'),p.bind(tmp_path/'RECEIPT.json')


@pytest.mark.parametrize('sid,ids',[('S03',['N_S03']),('S04',['Q_NAN','Q_GIRL','N_S04'])])
def test_real_source_case_audio_modes_quotes_faces_are_consumed_by_actual_graph(tmp_path,sid,ids):
    def short(c):c['decisions'][-1]['oral_suggestion']['text']='咱们哪有力气打。'
    case,r=inputs(tmp_path,short);folder=tmp_path/sid
    mapping={'s010':'A_LEAVE'} if sid=='S03' else {'s010':'Q_NAN','s012':'Q_GIRL','s014':'A_STOP'}
    result=a.materialize(folder,p.bind(OLD/'segments'/sid/'SOURCE_CASE.json'),case,r,ids,action_span_map=mapping)
    assert result['status']=='fresh_source_case_ready_for_actual_asset_tail_gate'
    entry=p.read(result['source_case']['path'])['shots'][0]
    if sid=='S03':assert [v['mode'] for v in entry['audio']]==['voiceover']
    else:
        assert [v['mode'] for v in entry['audio']]==['onscreen']*3
        assert entry['audio'][-1]['speaker']=='ye_dong'
        for audio in entry['audio']:
            for beat in entry['camera_beats']:
                if audio['start']<beat['end'] and audio['end']>beat['start']:
                    assert 'face' in beat['actors'][audio['speaker']]['visible_parts']
    proof=a.prove_graph(folder,result['source_case'],p.bind(OLD/'segments'/sid/'LIBRARY_INPUT.json'),p.bind(OLD/'H3_CONFIG.json'))
    assert proof['model_posts']==0 and proof['reference_count']==9 and proof['actual_LoadImage_count']==9
    graph=p.read(proof['graph']['path'])
    assert graph['guide_start']['inputs']['positive']==['condition',0]
    assert ('中性旁白以画外声叙述' in graph['condition']['inputs']['prompt']) is (sid=='S03')
    entry=p.read(result['source_case']['path'])['shots'][0]
    timings={i['case_event_id']:i for i in entry['narration_action_bindings']}
    if sid=='S03':assert entry['audio'][0]['start']>=timings['A_LEAVE']['end']
    else:assert entry['audio'][-1]['start']>=timings['A_STOP']['end']


def test_long_target_audio_returns_machine_split_notice_without_truncation(tmp_path):
    def long(c):c['decisions'][-1]['oral_suggestion']['text']='咱们饭都不够吃，身体这么虚弱，走路都没有力气，怎么能够跟他动手打架呢。'
    case,r=inputs(tmp_path,long);folder=tmp_path/'split'
    value=a.materialize(folder,p.bind(OLD/'segments/S04/SOURCE_CASE.json'),case,r,['Q_NAN','Q_GIRL','N_S04'],action_span_map={'s010':'Q_NAN','s012':'Q_GIRL','s014':'A_STOP'})
    assert value['status']=='needs_segment_split' and not (folder/'SOURCE_CASE.json').exists()
    assert value['details']['silent_truncation'] is False


def test_missing_actor_asset_returns_machine_notice_before_source_case(tmp_path):
    case,r=inputs(tmp_path);original=p.read(OLD/'segments/S03/SOURCE_CASE.json')
    original['shots'][0]['canonical_characters']['ye_nan']={'path':str(tmp_path/'missing_actor.png'),'sha256':'0'*64}
    source=tmp_path/'MISSING_ASSET_SOURCE.json';p.freeze(source,original)
    value=a.materialize(tmp_path/'missing',p.bind(source),case,r,['N_S03'],action_span_map={'s010':'A_LEAVE'})
    assert value['status']=='needs_asset' and not (tmp_path/'missing/SOURCE_CASE.json').exists()


def test_missing_or_unaccepted_receipt_cannot_create_a_source_case(tmp_path):
    case,r=inputs(tmp_path);raw=p.read(r['path']);raw['status']='needs_semantic_repair'
    bad=tmp_path/'BAD_RECEIPT.json';p.freeze(bad,raw)
    with pytest.raises(ValueError,match='accepted_v2'):
        a.materialize(tmp_path/'bad',p.bind(OLD/'segments/S03/SOURCE_CASE.json'),case,p.bind(bad),['N_S03'])


def test_old_camera_time_cannot_be_reused_without_explicit_action_binding(tmp_path):
    case,r=inputs(tmp_path)
    value=a.materialize(tmp_path/'no_map',p.bind(OLD/'segments/S03/SOURCE_CASE.json'),case,r,['N_S03'])
    assert value['status']=='needs_action_binding' and not (tmp_path/'no_map/SOURCE_CASE.json').exists()


def test_deterministic_split_keeps_warning_together_and_oral_after_stop(tmp_path):
    case,r=inputs(tmp_path)
    result=a.split_warning_segment(tmp_path/'split_chain',p.bind(OLD/'segments/S04/SOURCE_CASE.json'),case,r)
    assert [part['quote_ids'] for part in result['parts']]==[['Q_NAN','Q_GIRL'],['N_S04']]
    assert result['source_dialogue_coverage_exactly_once'] and result['actual_future_tail_claimed'] is False
    first=p.read(result['parts'][0]['result']['source_case']['path'])['shots'][0]
    second=p.read(result['parts'][1]['result']['source_case']['path'])['shots'][0]
    assert [audio['speaker'] for audio in first['audio']]==['ye_nan','ye_yaner']
    assert second['audio'][0]['speaker']=='ye_dong'
    anchor=next(b for b in second['narration_action_bindings'] if b['case_event_id']=='A_STOP')
    assert second['audio'][0]['start']>=anchor['end']
    assert result['parts'][1]['predecessor_required']=='P01_new_saved_actual_tail_not_yet_available'


def test_source_consumer_independently_rejects_voice_during_an_after_action(tmp_path,monkeypatch):
    case,r=inputs(tmp_path)
    original=a.policy.compile_before_video
    def wrong(*args):
        compiled=original(*args)
        action=next(i for i in compiled['items'] if i['id']=='A_LEAVE')
        audio=next(i for i in compiled['audio_items'] if i['id']=='N_S03')
        audio['start']=action['start']
        return compiled
    monkeypatch.setattr(a.policy,'compile_before_video',wrong)
    with pytest.raises(ValueError,match='approved_action_gap'):
        a.materialize(tmp_path/'bad_after',p.bind(OLD/'segments/S03/SOURCE_CASE.json'),case,r,['N_S03'],action_span_map={'s010':'A_LEAVE'})


def test_source_evidenced_listening_reaction_overlaps_girl_without_hiding_actor(tmp_path):
    case,r=inputs(tmp_path);folder=tmp_path/'parallel'
    variant=a.reaction_schedule_variant(folder,case,r)
    result=a.materialize(folder,p.bind(OLD/'segments/S04/SOURCE_CASE.json'),case,r,['Q_NAN','Q_GIRL','N_S04'],
        action_span_map={'s010':'Q_NAN','s012':'Q_GIRL','s014':'A_STOP'},scheduling_variant=variant)
    assert result['status']=='fresh_source_case_ready_for_actual_asset_tail_gate'
    entry=p.read(result['source_case']['path'])['shots'][0]
    girl=next(audio for audio in entry['audio'] if audio['speaker']=='ye_yaner');dong=entry['audio'][-1]
    stop=next(binding for binding in entry['narration_action_bindings'] if binding['case_event_id']=='A_STOP')
    assert stop['start']>=girl['start'] and stop['end']==girl['end'] and dong['start']>=stop['end']
    for beat in entry['camera_beats']:
        if beat['start']<stop['end'] and beat['end']>stop['start']:
            assert {'ye_yaner','ye_dong'}<=set(beat['actors']) and beat['framing']=='medium'
            assert 'face' in beat['actors']['ye_yaner']['visible_parts']
