"""Bound event-contract recovery without falling back to legacy field patches."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from .creative_event_script import EVENT_SCHEMA, compile_event_script
from .creative_review_gate import digest
from .creative_workflow_contract import CreativeContractError

def _save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def validate_revision_recovery_scope(name, original, corrected):
    """A scoped revision projection cannot accept events moved to another beat."""
    if not name.startswith("writer_revise"):
        return
    before=original.get("beats", [])
    after=corrected.get("beats", [])
    if [b.get("id") for b in before] != [b.get("id") for b in after]:
        raise CreativeContractError('局部返修的结构恢复不能改变节拍ID或顺序；需返回创作修订')
    for left,right in zip(before,after):
        if left.get("events") != right.get("events"):
            raise CreativeContractError('局部返修的结构恢复不能跨拍移动动作/对白，合并投影会丢事件；需返回创作修订')

def repair_event_contract(workflow,name,role,payload,original,error,validator,*,_attempt=1,_previous=None):
    path=workflow.run_dir/(name+'__event_contract_repair'+('' if _attempt==1 else '__02')+'.json')
    prompt=workflow.state['writer_prompt_binding']['prompt']+'''
本次仅修复events事件接口。返回完整事件稿，不返回before/during/after、patches或旧接口字段。
每拍最多两条dialogue；原拍超过时允许分成相邻节拍，在总时长不变的前提下分配整数秒。
所有原action/dialogue事件的kind、speaker、text和全片出现顺序逐字保留，不增删改动作或台词，不合并跨说话人的句子。只调整节拍边界、相应event/trigger概括、ID及时间。
禁止用人物背景或摘要替代任何原演出；不能凭接口修复改变剧情。
本次修复允许相邻dialogue，覆盖前文三种固定样例模式；缺少动作的位置由程序填无新增动作，模型不添加占位事件。
拆拍后可以只有一至两条原事件；不要为填满事件数创造新动作。'''
    if _attempt>1:prompt+='\n允许所有节拍重新分配秒数但全片总时长不变。对白中的连续省略号必须预留犹豫和反应：中文计时单位不超过(本拍秒数-2)*3.5；普通对白另留动作/反应，不照搬原拍的等长切分。'
    flexible=workflow.state['writer_prompt_binding']['creative_brief'].get('duration_policy')=='flexible'
    if flexible:
        prompt+='\n本简报总时长为可浮动参考，覆盖前述总时长不变要求；可按实际对白与反应需求调整秒数，但动作、对白及其顺序仍须逐字保留，局部返修不可跨拍移动事件。'
    if payload.get('revision_mode')=='full_script':
        prompt+='\n本次全稿返修将完整采纳所有事件，覆盖局部返修不可跨拍移动的要求；可拆拍并重编号，但全片原动作/对白及出现顺序必须完整保留。'
    request={'creative_brief':workflow.state['writer_prompt_binding']['creative_brief'],
             'original_events':original,'compilation_error':str(error)}
    if _previous is not None:request['previous_event_attempt']=_previous
    messages=[{'role':'system','content':prompt},
              {'role':'user','content':json.dumps(request,ensure_ascii=False)}]
    binding={'source_sha256':digest(original),'request_sha256':digest(messages)}
    if path.exists():
        record=json.loads(path.read_text(encoding='utf-8'))
        if any(record.get(k)!=v for k,v in binding.items()):
            raise RuntimeError('事件修复来源或请求改变')
        if record['status'] not in ('response_received','validated'):
            raise RuntimeError('事件修复响应未确认；禁止重复付费')
    else:
        if workflow.state['calls_started']>=workflow.max_calls:
            raise RuntimeError('事件修复调用预算已满')
        if workflow.state.get('contract_repairs_used',0)>=workflow.max_contract_repairs:
            raise RuntimeError('事件契约修复额度已满')
        budget=workflow._reserve_tokens(role,messages,max_tokens=12000)
        record={'schema':'creative_event_contract_repair/v1',**binding,
                'status':'pending_response','role':role,'request':messages,
                'context_budget':budget,'created_at':datetime.now(timezone.utc).isoformat()}
        _save(path,record)
        workflow.state['calls_started']+=1
        workflow.state['contract_repairs_used']=workflow.state.get('contract_repairs_used',0)+1
        workflow._save()
        try:
            schema=deepcopy(EVENT_SCHEMA)
            schema['properties']['beats']['items']['properties']['events']['minItems']=1
            response=workflow._call_model(role,messages,max_tokens=12000,
                temperature=0.2,thinking='disabled',structured_schema=schema)
        except Exception as exc:
            record.update(status='call_failed_or_uncertain',error=str(exc));_save(path,record);raise
        record.update(status='response_received',response_text=response.text,response_metadata=response.metadata)
        _save(path,record)
    if record['response_metadata'].get('finish_reason') not in (None,'stop','tool_calls'):
        raise CreativeContractError('事件修复输出未完整结束')
    corrected=workflow._decode(name,role,record['response_text'])
    if payload.get("revision_mode") != "full_script":
        validate_revision_recovery_scope(name,original,corrected)
    compiled=compile_event_script(corrected)
    def flatten(value):
        try:
            return [(e['kind'],e['speaker'],e['text']) for b in value['beats'] for e in b['events']]
        except (KeyError, TypeError) as exc:
            raise CreativeContractError('原事件缺失实际动作/对白内容，不能无损结构修复') from exc
    if flatten(corrected)!=flatten(original):
        raise CreativeContractError('事件修复改变了实际动作/对白或播放顺序，不能作为结构修复采用')
    if not flexible and sum(b['duration_seconds'] for b in corrected['beats'])!=sum(b['duration_seconds'] for b in original['beats']):
        raise CreativeContractError('事件修复改变了全片总时长')
    if name.startswith("writer_revise"):
        from .creative_workflow_contract import compile_beat_screenplay
        compiled["screenplay_markdown"]=compile_beat_screenplay(compiled)
    try:
        validator(compiled)
    except CreativeContractError as exc:
        record['compiled_validation_error']=str(exc);_save(path,record)
        if _attempt>=2:raise
        return repair_event_contract(workflow,name,role,payload,original,str(exc),validator,
            _attempt=2,_previous=corrected)
    record.update(status='validated',event_output=corrected,output=compiled,
                  output_sha256=digest(compiled),actual_events_preserved=True,
                  semantic_approval=False)
    _save(path,record)
    return deepcopy(compiled)
