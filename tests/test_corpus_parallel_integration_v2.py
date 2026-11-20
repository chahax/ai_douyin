import hashlib
import json
from types import SimpleNamespace

import pytest

from src.content_factory.corpus_screenplay_v1 import prepare, execute, read
from test_corpus_screenplay import put
from test_screenplay_revision_v4 import V4Client


def source_files(tmp_path,count=3):
    rows=[]
    for i in range(1,count+1):
        text=f'第{i}章：小周将钥匙交给老陈。两人确认交接后点头。'
        chapter={'index':i,'book_id':'fixture','text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
        path=put(tmp_path/f'chapter{i}.json',chapter)
        rows.append({'path':str(path),'sha256':chapter['sha256']})
    manifest=put(tmp_path/'MANIFEST.json',{'status':'accessible_catalogue_complete','book_id':'fixture',
        'book_name':'并行测试资料','chapters':rows})
    previous=put(tmp_path/'HISTORY.json',{'calls_started':7,'reported_tokens':800})
    return manifest,previous


class IntegratedClient(V4Client):
    def __init__(self):
        super().__init__()
        self.parallel_calls=[]

    def call(self,role,messages,**kwargs):
        p=json.loads(messages[-1]['content'])
        if 'core_chapters' in p:
            passages={c['index']:next(s for s in p['source_passages'] if s['chapter_index']==c['index'])
                      for c in p['core_chapters']}
            out={'group_id':p['group_id'],'chapter_indices':p['chapter_indices'],'conflicts':[],
                 'claims':[{'id':f"{p['group_id']}-C{i:03d}",'kind':'event','subject':'交接',
                   'statement':passages[c['index']]['text'],'chapter_index':c['index'],'temporal_status':'occurring',
                   'evidence_ids':[passages[c['index']]['id']],'entities':[]}
                   for i,c in enumerate(p['core_chapters'],1)]}
        elif 'entity_candidates' in p:
            out={'world':[],'characters':[],'locations':[],'conflicts':[],'omitted_claims':[],
                 'design_proposals':[],'timeline':[{'id':c['id'],'chapter_index':c['chapter_index'],
                  'temporal_status':c['temporal_status'],'statement':c['statement'],
                  'claim_ids':[c['id']],'character_ids':[],'location_ids':[]}
                  for c in p['claims']]}
        elif 'source_contexts' in p:
            out={'decision':'pass','checked_claim_ids':[c['id'] for c in p['claims']],
                 'issues':[]}
        else:
            if role=='writer':
                assert p['global_bible']['validation']['downstream_ready']
                assert p['episode_brief']['chapter_indices']==[1,2]
            r=super().call(role,messages,**kwargs)
            r.metadata.update(prompt_tokens=80,completion_tokens=20,total_tokens=100,finish_reason='stop')
            return r
        self.parallel_calls.append(p)
        return SimpleNamespace(text=json.dumps(out,ensure_ascii=False),
            metadata={'prompt_tokens':80,'completion_tokens':20,'total_tokens':100,'finish_reason':'stop'},
            response_payload={})


def test_new_default_full_path_preserves_global_context_to_writer(tmp_path):
    manifest,previous=source_files(tmp_path);run=tmp_path/'run'
    plan=prepare(manifest,run,user_statement='开发测试',previous_status=previous,analysis_group_chars=30)
    assert plan['parallel_analysis']['workers']==2 and len(plan['groups'])==3
    client=IntegratedClient();state=execute(run,client)
    assert state['status']=='reviewed_draft_ready' and state['source_chapters']==3
    assert len(client.parallel_calls)==5 and client.writers==1
    assert state['total_calls_with_history']==7+state['calls_started']
    assert state['pending'] is None and state['pending_calls']=={}
    assert read(run/'GLOBAL_ANALYSIS.json')['semantic_status']=='machine_review_passed'
    before=state['calls_started'];assert execute(run,client)['calls_started']==before


def test_analysis_only_is_frozen_and_never_starts_writer(tmp_path):
    manifest,previous=source_files(tmp_path);run=tmp_path/'run'
    prepare(manifest,run,user_statement='仅分析测试',previous_status=previous,analysis_only=True)
    client=IntegratedClient();state=execute(run,client)
    assert state['status']=='analysis_ready' and client.writers==0 and state['calls_started']==3
    assert not (run/'SELECTION.json').exists()
    assert execute(run,client)==state


def test_frozen_parallel_plan_cannot_change_workers_or_budget(tmp_path):
    manifest,previous=source_files(tmp_path);run=tmp_path/'run'
    prepare(manifest,run,user_statement='开发测试',previous_status=previous)
    plan=read(run/'PLAN.json');plan['parallel_analysis']['workers']=4;put(run/'PLAN.json',plan)
    with pytest.raises(ValueError,match='frozen_plan_changed'):execute(run,IntegratedClient())


def test_local_route_rejected_for_automatic_writer_without_network(tmp_path):
    manifest,previous=source_files(tmp_path)
    with pytest.raises(ValueError,match='requires_analysis_only'):
        prepare(manifest,tmp_path/'run',user_statement='开发测试',previous_status=previous,
            analysis_route={'provider':'ollama','model':'model','endpoint':'http://127.0.0.1:11435'})


def test_local_analysis_plan_displays_actual_model_and_no_writer(tmp_path,monkeypatch):
    from src.content_factory import corpus_local_analysis_v2 as local
    monkeypatch.setattr(local,'preflight',lambda route:{**route,'digest':'fixture-pinned'})
    manifest,previous=source_files(tmp_path)
    plan=prepare(manifest,tmp_path/'run',user_statement='仅本机分析测试',previous_status=previous,
                 analysis_only=True,analysis_route={'provider':'ollama','model':'fixture-qwen',
                     'endpoint':'http://127.0.0.1:11435'})
    assert plan['models']=={'analysis_review':'fixture-qwen','writer':None}


def test_sixty_nine_chapter_fixture_reaches_one_merge_without_losing_last_group(tmp_path):
    manifest,previous=source_files(tmp_path,69);run=tmp_path/'run'
    plan=prepare(manifest,run,user_statement='69章调度合同测试',previous_status=previous,
                 analysis_only=True,analysis_workers=4,analysis_group_chars=160)
    client=IntegratedClient();state=execute(run,client)
    assert state['status']=='analysis_ready' and state['source_chapters']==69
    summary=read(run/'GLOBAL_ANALYSIS.json')
    assert sorted(t['chapter_index'] for t in summary['timeline'])==list(range(1,70))
    assert sum('entity_candidates' in p for p in client.parallel_calls)==1
    assert sum('source_contexts' in p for p in client.parallel_calls)==1
    assert state['calls_started']==len(plan['groups'])+2
