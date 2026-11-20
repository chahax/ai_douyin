import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from source_media_fixture import complete_media_analysis
from test_pre_video_script import _row, _expanded_rows, _Repository, _Profiles, NOW
from src.trend_intelligence.media_evidence import (
    media_readiness, batch_media_readiness, build_expression_patterns, SourceMediaGateError)
from src.trend_intelligence.pre_video_script import PreVideoScriptService, PreVideoScriptRequest
from src.trend_intelligence.repository import TrendRepository


@pytest.fixture(autouse=True)
def media_gate_uses_isolated_output_root(monkeypatch):
    monkeypatch.setattr(PreVideoScriptService, '_resolve_output_dir',
                        staticmethod(lambda request: Path(request.output_dir).resolve()))


def test_metadata_batch_cannot_reach_writer_and_has_actionable_report(tmp_path):
    rows = _expanded_rows([
        _row('labor','解除合同如何处理',video_type='mixed',metric=100_000),
        _row('marriage','离婚材料争议',video_type='mixed',metric=100_000)])
    class NeverCalled:
        def generate_json(self, *args, **kwargs):
            pytest.fail('Writer must not run on metadata-only sources')
    service = PreVideoScriptService(repository=_Repository([r[0] for r in rows],[r[1] for r in rows]),
        profile_repository=_Profiles(),script_client=NeverCalled())
    request=PreVideoScriptRequest(account_key='account01',recent_video_types=('mixed',),output_dir=str(tmp_path))
    assert service.source_media_readiness(request,now=NOW)['ready_count']==0
    with pytest.raises(SourceMediaGateError) as caught:
        service.generate(request,now=NOW)
    report=json.loads(Path(caught.value.result['report_path']).read_text(encoding='utf-8'))
    assert len(report['missing'])==20 and report['ready_count']==0
    assert report['script_generation_submitted'] is False
    assert all(r['url'] for r in report['sources'])
    assert not list(tmp_path.glob('detailed-script*'))


def test_complete_evidence_round_trip_and_tamper_blocks(tmp_path):
    _, analysis=_row('one','演示材料差异',video_type='mixed',metric=100_000)
    analysis=complete_media_analysis(analysis,tmp_path/'assets')
    assert media_readiness(analysis)['ready']
    repository=TrendRepository(tmp_path/'trend.db')
    repository.save_content_analysis(analysis)
    loaded=repository.get_content_analysis(analysis.analysis_id)
    assert loaded.expression_analysis==analysis.expression_analysis
    assert loaded.media_evidence==analysis.media_evidence
    Path(analysis.media_evidence['source_video_path']).write_bytes(b'changed video')
    result=media_readiness(loaded)
    assert not result['ready'] and any('内容已变化' in x for x in result['reasons'])


@pytest.mark.parametrize('breakage',['untimed','missing_asr','wrong_evidence','incomplete_frames','no_speech_without_reason','cross_channel','tampered_frame'])
def test_incomplete_or_unbacked_claims_do_not_count_as_analyzed(tmp_path,breakage):
    _, analysis=_row('one','演示材料差异',video_type='mixed',metric=100_000)
    analysis=complete_media_analysis(analysis,tmp_path/'assets')
    expression=analysis.expression_analysis
    if breakage=='untimed': expression['evidence'][0]['start_seconds']=None
    elif breakage=='missing_asr': expression['evidence']=expression['evidence'][:1]
    elif breakage=='wrong_evidence': expression['core_message']['evidence_ids']=['fabricated']
    elif breakage=='incomplete_frames': analysis.media_evidence['visual']['analyzed_frame_count']=2
    elif breakage=='cross_channel': expression['visual_expression'][0]['evidence_ids']=['A0001']
    elif breakage=='tampered_frame': (tmp_path/'assets'/'frame_0.jpg').write_bytes(b'changed')
    else: analysis.media_evidence['audio']['status']='verified_no_speech'
    assert not media_readiness(analysis)['ready']


@pytest.mark.parametrize('start,end',[(-1.,6.),(0.,60.),(5.,1.)])
def test_audio_coverage_must_stay_within_actual_video(tmp_path,start,end):
    _, analysis=_row('one','材料演示',video_type='mixed',metric=100_000)
    analysis=complete_media_analysis(analysis,tmp_path/'assets')
    analysis.media_evidence['audio'].update(coverage_start_seconds=start,coverage_end_seconds=end)
    assert not media_readiness(analysis)['ready']


@pytest.mark.parametrize('channel',['visual','asr'])
def test_evidence_cannot_change_decoded_time_or_recognized_words(tmp_path,channel):
    from src.trend_intelligence.media_evidence import file_sha256
    _, analysis=_row('one','材料演示',video_type='mixed',metric=100_000)
    analysis=complete_media_analysis(analysis,tmp_path/'assets')
    row=next(e for e in analysis.expression_analysis['evidence'] if e['channel']==channel)
    if channel=='visual': row.update(start_seconds=.5,end_seconds=.5)
    else: row['text']='编造的转写'
    # Even a re-saved synthesis artifact cannot change extraction evidence.
    visual=analysis.media_evidence['visual']
    path=Path(visual['artifact_path'])
    payload=json.loads(path.read_text(encoding='utf-8'))
    payload['answer']['expression_analysis']=analysis.expression_analysis
    path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    visual['artifact_sha256']=file_sha256(path)
    result=media_readiness(analysis)
    assert not result['ready']
    assert any('实际帧或转写不匹配' in reason for reason in result['reasons'])


def test_missing_results_not_hidden_by_twenty_successes(tmp_path):
    analyses=[]
    for i in range(20):
        _, analysis=_row(f'v{i}','材料演示',video_type='mixed',metric=100_000)
        analyses.append(complete_media_analysis(analysis,tmp_path/f'v{i}'))
    report=batch_media_readiness(analyses,expected_item_ids=[a.item_id for a in analyses]+['missing'])
    assert report['ready_count']==20 and not report['ready']
    assert report['missing'][-1]['item_id']=='missing'
    for analysis in analyses[1:]:
        analysis.media_evidence['source_video_path']=analyses[0].media_evidence['source_video_path']
        analysis.media_evidence['source_video_sha256']=analyses[0].media_evidence['source_video_sha256']
    repeated=batch_media_readiness(analyses,verify_artifacts=False)
    assert repeated['ready_count']==1 and len(repeated['missing'])==19
    assert not repeated['ready']


def test_high_like_patterns_are_observed_counts_not_contribution_percent(tmp_path):
    cohort=[]
    for i,metric in enumerate([100,200,300,400,500,600,700,800]):
        observation,analysis=_row(f'v{i}','材料演示',video_type='mixed',metric=metric)
        observation.metric_kind='likes'
        mode='prop_demonstration' if i>=6 else 'question_answer'
        analysis=complete_media_analysis(analysis,tmp_path/f'v{i}',mode=mode)
        cohort.append(SimpleNamespace(observation=observation,analysis=analysis,relevance=80.))
    # A very large view count is a separate comparator, never extra likes.
    observation,analysis=_row('views','材料演示',video_type='mixed',metric=1_000_000)
    analysis=complete_media_analysis(analysis,tmp_path/'views')
    cohort.append(SimpleNamespace(observation=observation,analysis=analysis,relevance=90.))
    report=build_expression_patterns(cohort)
    assert report['creative_contribution_percent'] is None
    prop=next(p for p in report['patterns'] if p['mode']=='prop_demonstration')
    likes=next(g for g in prop['metric_groups'] if g['metric_kind']=='likes')
    assert likes['high_group_support']==2 and likes['high_group_size']==2
    assert likes['comparison_group_support']==0 and likes['comparison_group_size']==6
    assert likes['median_metric_with_mode']==750
    assert likes['median_metric_without_mode']==350
    assert 'views' not in likes['high_source_item_ids']
    for item in cohort: item.observation.metric_value=100
    tied=build_expression_patterns(cohort)
    assert all(not g['contrast_available'] for p in tied['patterns'] for g in p['metric_groups'])


def test_new_metadata_does_not_hide_complete_media_for_same_source(tmp_path):
    observation,metadata=_row('one','材料演示',video_type='mixed',metric=100_000)
    complete=complete_media_analysis(copy.deepcopy(metadata),tmp_path/'one')
    service=PreVideoScriptService(repository=_Repository([observation],[metadata,complete]),profile_repository=_Profiles())
    request=PreVideoScriptRequest(account_key='account01',recent_video_types=('mixed',))
    candidates=service._recent_candidates(_Profiles().get('account01'),request,NOW)
    assert candidates[0].analysis.status=='completed'


def test_stored_analysis_cannot_bypass_later_semantic_rejection(tmp_path,monkeypatch):
    from src.trend_intelligence.content_analysis import artifacts
    original_check=artifacts.require_no_semantic_rejection
    monkeypatch.setattr(artifacts,'require_no_semantic_rejection',
        lambda path: original_check(path,rejection_root=tmp_path/'rejections'))
    _, analysis=_row('one','材料演示',video_type='mixed',metric=100_000)
    analysis=complete_media_analysis(analysis,tmp_path/'assets')
    assert media_readiness(analysis)['ready']
    review_path=tmp_path/'assets'/'semantic_review.json'
    review={'schema':'source_expression_semantic_review/v1',
        'artifact_sha256':analysis.media_evidence['visual']['artifact_sha256'],
        'decision':'failed','blocked_for_script_generation':True,
        'observations':[{'notes':'候选核心误改原句条件'}]}
    review_path.write_text(json.dumps(review),encoding='utf-8')
    assert not media_readiness(analysis)['ready']
    review.update(decision='passed',blocked_for_script_generation=False)
    review_path.write_text(json.dumps(review),encoding='utf-8')
    assert not media_readiness(analysis,verify_artifacts=False)['ready']
