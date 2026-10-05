from copy import deepcopy
import pytest
from scripts import run_creative_s7_row_group_v27 as r
from scripts import creative_synchronous_prop_contract_v3 as compact
from scripts import creative_local_event_performance_v3 as split


def fixture():
    c=deepcopy(r.previous.context());b=deepcopy(c['raw_linear_script']['beats'][2]);b['steps']=b['steps'][:1];c['raw_linear_script']['beats']=[b]
    raw={'schema':r.SCALAR_FILM,'emotional_arc':'清单压力','causal_chain':'整体摊开','ending_intent':'可见清单',b['id']:'整组清单|三色纸与手|桌面近景|信息可见后|默认接活|整体横排|无对白'}
    film=r.decode_scalar_film(raw,c);state={}
    for person in c['static_visual_manifest']['characters']:
        state[person['id']]={'posture':'standing' if person['id']=='C01' else 'sitting','position':'方澄工位' if person['id']=='C01' else '林屿工位','gaze':'桌面','affect':'平静','facing':'E01' if person['id']=='C01' else 'E02'}
    for prop in c['static_visual_manifest']['props']:state[prop['id']]={'holder':'none','location':'surface:E02:desk'}
    for pid in compact.MEMBERS:state[pid]['location']='surface:E01:corner_stack'
    opening={'schema':r.STATE,'context_sha256':r.control.digest(c),'initial_state':state,'spatial_contract':{'seats':[]}}
    win={'schema':r.WINDOWS,'context_sha256':r.control.digest(c),'film_plan_sha256':r.control.digest(film),'shots':[{'shot_id':'SH01','requirements':[]}]}
    d=r.assemble_direction(c,film,opening,win);inp=r.physical.build_local_input(c,d,[]);ref='raw_linear_script.beats.0.steps.0'
    take=[{'kind':'take','actor':'C02','target':pid,'value':'右手'} for pid in sorted(compact.MEMBERS)]
    place=[{'kind':'place','actor':'C02','target':pid,'value':'surface:E02:left_front'} for pid in sorted(compact.MEMBERS)]
    plan={'actions':[{'source_step_ref':ref,'events':[{'intent':'整叠拿起','subject':'C02','operation':take,'satisfies':[]},{'intent':'整组摊开并一次压黄角','subject':'C02','operation':place,'satisfies':[]}]}]}
    return c,d,inp,plan


def test_three_member_batch_commits_once_per_authored_event():
    c,d,inp,plan=fixture()
    doc=split.plan_as_compact(plan,inp)
    derived=compact.derive_local(doc,inp)
    result=r.physical.compile_complete(c,d,[derived])
    assert result['total_duration_seconds']==2
    assert len(result['source_trace'])==2
    assert all(len(x['physical_operations'])==3 for x in result['source_trace'])
    assert [x['operations'] for x in derived['step_units'][0]['groups']]==[plan['actions'][0]['events'][0]['operation'],plan['actions'][0]['events'][1]['operation']]
    assert result['semantic_approval'] is False


def test_mixed_kind_duplicate_actor_and_unregistered_source_rejected():
    c,d,inp,plan=fixture()
    for mutate in ('kind','actor','duplicate'):
        bad=deepcopy(plan);ops=bad['actions'][0]['events'][0]['operation']
        if mutate=='kind':ops[1]['kind']='place'
        elif mutate=='actor':ops[1]['actor']='C01'
        else:ops[1]['target']=ops[0]['target']
        with pytest.raises(ValueError):compact.derive_local(split.plan_as_compact(bad,inp),inp)
    wrong=deepcopy(inp);wrong['context']['raw_linear_script']['beats'][0]['steps'][0]['text']='只有普通手部动作'
    with pytest.raises(ValueError):compact.derive_local(split.plan_as_compact(plan,wrong),wrong)


def test_each_member_still_requires_unheld_group_start_state():
    c,d,inp,plan=fixture();d['initial_state']['P03_Y']['holder']='C01';d['initial_state']['P03_Y']['location']='左手'
    inp=r.physical.build_local_input(c,d,[]);derived=compact.derive_local(split.plan_as_compact(plan,inp),inp)
    with pytest.raises(Exception,match='PLAN_GROUP_PRECONDITION_INVALID|STATE'):
        r.physical.compile_complete(c,d,[derived])
