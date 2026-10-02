import pytest
from scripts.run_cohort_expression_trial import evidence_card, observed_window
from src.trend_intelligence.narrative_workflow import identity
import json

def test_preserve_all_claim_rows_not_just_endpoints():
    source={k:'value' for k in ('source_id','title','metric_kind','metric_value','collected_at','published_at')}
    source['expression_analysis']={'core_message':{'text':'core','evidence_ids':['A1','A2','A3']},'evidence':[{'id':k} for k in ['A1','A2','A3','A4']]}
    result=evidence_card(source)
    assert [r['id'] for r in result['expression_analysis']['evidence']]==['A1','A2','A3']
    assert len(source['expression_analysis']['evidence'])==4
    source['expression_analysis']['core_message']['evidence_ids'].append('unknown')
    with pytest.raises(ValueError):evidence_card(source)

@pytest.mark.parametrize('fault',['truncated','echo','multiline_echo','identity'])
def test_unusable_audio_never_becomes_usable_observation(tmp_path,fault):
    clip=tmp_path/'clip.mp4';clip.write_bytes(b'synthetic')
    window={'clip_path':str(clip),'clip_sha256':identity(clip)['sha256'],'source_start':0,'source_end':10}
    r={'video':str(clip),'source_sha256':window['clip_sha256'],'use_audio_in_video':True,'response':'synthetic ordinary observation','response_may_be_truncated':fault=='truncated'}
    if fault=='echo':r['response']='声音快慢、强弱及是否变化；一个实际可见'
    if fault=='multiline_echo':r['response']='一、声音快慢、强弱及是否变化；\n二、一个实际可见的表情或物件动作；\n三、声画是否相符或无法确认。'
    if fault=='identity':r['source_sha256']='wrong'
    path=tmp_path/'result.json';path.write_text(json.dumps(r),encoding='utf-8')
    if fault=='identity':
        with pytest.raises(ValueError):observed_window(path,window)
    else:
        observation,_=observed_window(path,window)
        assert observation['quality_warnings'] and observation['observation']=='不可用观察；原始结果保留供复核。'


def test_comparison_cannot_invent_metric_or_support():
    from scripts.run_cohort_expression_trial import verify_comparison
    rows=[{'source_id':str(i),'metric_kind':'likes_user_confirmed','metric_value':i,'expression_analysis':{'expression_modes':[{'mode':'demo'}]}} for i in range(1,5)]
    stored={'source_count':4,'high_group_threshold':4,'high_group_size':1,'multi_label':True,'types':[{'mode':'demo','n':4,'source_ids':['1','2','3','4'],'median_likes':2.5,'high_ids':['4'],'comparison_ids':['1','2','3']}]}
    assert verify_comparison(rows,stored)==stored
    stored['types'][0]['median_likes']=999
    with pytest.raises(ValueError):verify_comparison(rows,stored)


def test_digest_keeps_every_source_and_cited_middle_time():
    from scripts.run_cohort_expression_trial import research_digest
    source={k:'synthetic' for k in ('source_id','title','metric_value','metric_kind','primary_tag','original_duration_seconds')}
    source['expression_analysis']={k:[] for k in ('expression_modes','visual_expression','audio_expression','conflict','uncertainties')}
    source['expression_analysis'].update(core_message={'text':'reviewed core','evidence_ids':['A1','A2','A3']},
        evidence=[{'id':f'A{i}','start_seconds':i,'end_seconds':i+1,'text':'full raw body'} for i in (1,2,3)])
    source['acoustic_hypotheses']={'window_label_counts':{},'limitations':['unverified']}
    source['audio_visual_observations']=[{'quality_warnings':[]}]
    result=research_digest({'sources':[dict(source,source_id=str(i)) for i in range(20)]})
    assert [s['source_id'] for s in result['sources']]==[str(i) for i in range(20)]
    assert result['sources'][0]['reviewed_expression']['core_message']==source['expression_analysis']['core_message']
    assert result['sources'][0]['source_local_evidence_times']['A2']==[2,3]
    assert source['expression_analysis']['evidence'][1]['text']=='full raw body'


def test_partial_review_cannot_pass_invented_story_or_unreviewed_remainder():
    from scripts.run_cohort_expression_trial import reviewed_summary_text
    body='actual model direction\nrejected ending'
    review={'review_scope':'selected_direction_only','accepted_model_excerpts':['actual model direction'],
        'excluded_findings':['ending unsupported'],'author_constraints':['show actual result']}
    assert reviewed_summary_text(body,review)=='actual model direction'
    review['accepted_model_excerpts']=['reviewer invented replacement']
    with pytest.raises(ValueError):reviewed_summary_text(body,review)
