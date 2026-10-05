from copy import deepcopy
import json,pytest
from scripts import creative_verifiable_fault_memory_v1 as m
B={'raw_script_sha256':'s7','local_input_sha256':'same-start','current_shot':'SH03'}


def row(n,feedback,binding=B,label='plan_p003_r'):
 return {'ordinal':n,'label':label+str(n),'status':'contract_valid','request':{'input_provenance':deepcopy(binding),'messages':[{'role':'user','content':json.dumps({'verified_faults':feedback},ensure_ascii=False)}]}}


def test_complete_verified_requirements_survive_later_format_feedback_without_output_splice():
 earlier={'requirement':'浅黄从最初摊开就放左前'};later={'format_issue':'普通take不是混合数组'};rs=[row(1,earlier),row(2,later)];before=deepcopy(rs)
 result=m.build(rs,B,'plan_p003_r',{'issue':'仍漏侧身'})
 assert result['history'][0]['verified_feedback_inputs']==[earlier] and result['history'][1]['verified_feedback_inputs']==[later]
 assert rs==before and result['automatic_retry'] is False and result['model_output_manually_patched'] is False


@pytest.mark.parametrize('key',m.BINDING_KEYS)
def test_changed_input_cannot_blindly_inherit_old_feedback(key):
 changed=deepcopy(B);changed[key]='different'
 with pytest.raises(ValueError):m.build([row(1,{'issue':'old'},changed)],B,'plan_p003_r',{})


def test_other_shot_excluded_and_duplicate_identity_rejected():
 assert m.build([row(1,{'issue':'other'},label='plan_p004_r')],B,'plan_p003_r',{})['history']==[]
 with pytest.raises(ValueError):m.build([row(1,{}),row(1,{})],B,'plan_p003_r',{})
