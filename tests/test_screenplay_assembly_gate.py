import pytest
from scripts import assemble_screenplay_segments as assembly


@pytest.mark.parametrize('attempts', [[], [{'shot':'S01','series_id':'current','status':'awaiting_review'}],
    [{'shot':'S01','series_id':'old','status':'passed'}],
    [{'shot':'S01','series_id':'current','status':'passed'}, {'shot':'S01','series_id':'current','status':'failed'}]])
def test_assembly_cannot_use_old_or_superseded_approval(tmp_path, attempts):
    path=tmp_path/'campaign.json'
    assembly.c.write(path,{'shots':['S01'],'current_series_id':'current','attempts':attempts})
    with pytest.raises(ValueError,match='finish actual review'):
        assembly.approved_inputs(path)


@pytest.mark.parametrize('tamper', [None, 'plan', 'request', 'prompt'])
@pytest.mark.parametrize('schema', ['reviewed_cohort_segment/v1','reviewed_director_segment/v1','reviewed_reference_director_segment/v1'])
def test_reviewed_assembly_binds_source_and_submission(tmp_path, monkeypatch, tamper, schema):
    if schema=='reviewed_cohort_segment/v1':
        from scripts import run_cohort_video as source
    else:
        from scripts import run_director_video as source
    c=assembly.c
    folder=tmp_path/'segment';folder.mkdir()
    bundle_dir=tmp_path/'bundle';bundle_dir.mkdir()
    script={'shots':[{'shot_id':'S01'}]}
    c.write(bundle_dir/'bundle.json',{})
    c.write(folder/'locked_script.json',script)
    source_sha=c.file_sha(folder/'locked_script.json')
    binding={'path':str(bundle_dir/'script.json'),'sha256':source_sha}
    plan={'shot_id':'S01','previous_run':None,'bindings':{'story':binding}}
    c.write(folder/'trial_plan.json',plan)
    (folder/'S01.prompt.txt').write_text('approved prompt',encoding='utf8')
    c.write(folder/'request.preview.json',{'duration':7})
    (folder/'video.mp4').write_bytes(b'video')
    (folder/'tail.png').write_bytes(b'tail')
    review={'decision':'passed','source_sha256':c.file_sha(folder/'video.mp4'),
            'script_sha256':source_sha,'checks':dict.fromkeys(assembly.REVIEW_CHECKS,True)}
    c.write(folder/'review.json',review)
    c.write(folder/'production.json',{'trial_schema':schema,
        'bundle':str(bundle_dir),'bundle_sha256':c.file_sha(bundle_dir/'bundle.json'),
        'script_sha256':source_sha,'request_sha256':c.file_sha(folder/'request.preview.json')})
    c.write(folder/'S01.json',{'status':'downloaded','script_sha256':source_sha,
        'prompt_sha256':c.file_sha(folder/'S01.prompt.txt'),'request':{'duration':7},
        'local_video':str(folder/'video.mp4'),'video_sha256':review['source_sha256'],
        'last_frame':str(folder/'tail.png'),'last_frame_sha256':c.file_sha(folder/'tail.png')})
    campaign=tmp_path/'campaign.json'
    c.write(campaign,{'shots':['S01'],'current_series_id':'current','attempts':[{
        'shot':'S01','series_id':'current','status':'passed','run_dir':str(folder),
        'review_path':str(folder/'review.json'),'review_sha256':c.file_sha(folder/'review.json')}]})
    monkeypatch.setattr(source,'verify_bundle',lambda _:({'script':binding},script))
    monkeypatch.setattr(source,'execution_prompt',lambda *_:'approved prompt')
    if tamper=='plan':
        plan['previous_run']='unapproved';c.write(folder/'trial_plan.json',plan)
    if tamper=='request':c.write(folder/'request.preview.json',{'duration':9})
    if tamper=='prompt':(folder/'S01.prompt.txt').write_text('changed',encoding='utf8')
    if tamper:
        with pytest.raises(ValueError,match='Reviewed source, plan or submitted prompt changed'):
            assembly.approved_inputs(campaign)
    else:assert len(assembly.approved_inputs(campaign)[1])==1
