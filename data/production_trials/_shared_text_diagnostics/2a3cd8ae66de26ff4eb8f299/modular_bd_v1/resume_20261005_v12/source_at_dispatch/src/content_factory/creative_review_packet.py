"""Evidence-bound focused review. Program binds sources; model judges semantics."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from .creative_workflow_contract import CreativeContractError

VERSION = 'focused_review_packet_v1'
REVIEW_SCHEMA = 'focused_semantic_review/v1'
CHECKS = ('requirements', 'timing', 'continuity', 'dialogue_timing', 'first_frame', 'assets')
BLOCKED_REASONS = frozenset({'SOURCE_MISSING','REQUIRED_EVIDENCE_MISSING','REQUIREMENT_CONFLICT','EXPRESSION_UNSUPPORTED','CHECKER_NOT_EXECUTED'})
ADVISORY_REASONS = frozenset({'OPTIONAL_AESTHETIC','ACTUAL_MEDIA_AUDIO_PENDING','ACTUAL_MEDIA_LIPSYNC_PENDING','ACTUAL_MEDIA_VISUAL_PENDING'})
UNKNOWN_POLICY = {'schema_version':'review_unknown_policy/v1','default':'review_required','blocked_reason_codes':sorted(BLOCKED_REASONS),'advisory_reason_codes':sorted(ADVISORY_REASONS),'required_check_may_be_advisory':False,'unknown_counts_as_pass':False,'blocked_requires_source_repair':True}

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def _error(message):
    raise CreativeContractError('FOCUSED_REVIEW: '+message)

def _text(value,name):
    if not isinstance(value,str) or not value.strip(): _error(name+' must be nonempty text')

def _leaves(value,path=''):
    if isinstance(value,dict):
        for key,item in sorted(value.items()):
            if not isinstance(key,str) or '.' in key: _error('unresolvable source key: '+str(key))
            yield from _leaves(item,path+'.'+key if path else key)
    elif isinstance(value,list):
        for i,item in enumerate(value): yield from _leaves(item,path+'.'+str(i))
    else: yield path,value

def build_packet(context):
    """Preserve every semantic leaf, including compiled prompt and plan prose.

    Equal values share an ID. Sources and complete paths remain reconstructable;
    comparison groups refer to prefixes rather than repeat all evidence lists.
    Scheduled facts are retained: equivalence with the source is never presumed.
    """
    if not isinstance(context,dict): _error('context must be object')
    for root in ('script','shots','state_plan'):
        if not isinstance(context.get(root),dict) or not context[root]: _error('SOURCE_MISSING: '+root)
    shots=context['shots'].get('shots');beats=context['script'].get('beats');plans=context['state_plan'].get('beats')
    if not isinstance(shots,list) or not shots or not isinstance(beats,list) or not beats: _error('SOURCE_MISSING: shot/script rows')
    if not isinstance(plans,list) or len(plans)!=len(beats): _error('SOURCE_MISSING: full state_plan beats')
    if not isinstance(context['state_plan'].get('initial_state'),dict) or not context['state_plan']['initial_state']:_error('SOURCE_MISSING: state_plan.initial_state')
    if not (context.get('creative_brief') or context.get('brief')): _error('SOURCE_MISSING: brief')
    if not (context.get('static_manifest') or context.get('static_visual_manifest') or context['shots'].get('style')): _error('SOURCE_MISSING: static assets/style')
    sources={}; source_map={}; seen={}; omissions=[]
    for path,value in _leaves(context):
        if path=='script.screenplay_markdown':
            omissions.append({'path':path,'reason':'display-only Markdown; structured script retained'});continue
        key=json.dumps(value,ensure_ascii=False,sort_keys=True)
        if key not in seen:
            seen[key]='E'+str(len(sources)+1).zfill(4);sources[seen[key]]=value
        source_map[path]=seen[key]
    checks=[]; comparisons=[]; identifiers=[]
    for i,shot in enumerate(shots):
        if not isinstance(shot,dict): _error('invalid shot')
        sid=shot.get('id');_text(sid,'shot.id')
        if sid in identifiers:_error('duplicate shot id')
        identifiers.append(sid);own=f'shots.shots.{i}'
        for field in ('start_state','end_state','visible_performance','camera','cut_reason','prompt'):
            if not isinstance(shot.get(field),str) or not shot[field].strip() or not any(p==own+'.'+field or p.startswith(own+'.'+field+'.') for p in source_map): _error('REQUIRED_EVIDENCE_MISSING: '+own+'.'+field)
        beat_id=shot.get('beat_id') or shot.get('source_beat_id')
        bi=next((j for j,b in enumerate(beats) if b.get('id')==beat_id),None)
        script_root=f'script.beats.{bi}' if bi is not None else 'script'
        pi=[j for j,p in enumerate(plans) if p.get('beat_id')==beat_id] if bi is not None else []
        plan_root=f'state_plan.beats.{pi[0]}' if len(pi)==1 else 'state_plan'
        previous=f'shots.shots.{i-1}' if i else 'previous_shot'
        groups={'requirements':[own,script_root,'creative_brief','brief'],
                'timing':[own,script_root,plan_root,'scheduling_report'],
                'continuity':[own,previous,plan_root,'state_plan.initial_state','state_plan.spatial_contract'],
                'dialogue_timing':[own,script_root,'scheduling_report'],
                'first_frame':[own,previous,plan_root,'state_plan.initial_state'],
                'assets':[own,'shots.style','static_manifest','static_visual_manifest','production_design']}
        if context.get('final_video_prompts'):
            final_root=f'final_video_prompts.{i}'
            for kind in ('requirements','timing','first_frame'):
                groups[kind].append(final_root)
            comparisons.append({'kind':'authored_vs_compiled_prompt','location':sid,
                'left':[own,script_root],'right':[final_root]})
        for name,prefixes in groups.items():checks.append({'check_id':sid+':'+name,'location':sid,'kind':name,'required':True,'source_prefixes':prefixes})
        comparisons.extend([
            {'kind':'operations_vs_prose','location':sid,'left':[plan_root],'right':[own+'.visible_performance',own+'.prompt']},
            {'kind':'end_vs_next_start','location':sid,'left':[previous+'.end_state'] if i or context.get('previous_shot') else ['state_plan.initial_state'],'right':[own+'.start_state']},
            {'kind':'cut_vs_unfinished_tasks','location':sid,'left':[own+'.camera',own+'.cut_reason',plan_root],'right':[script_root,'scheduling_report']}])
    _compress_sources(sources)
    tree={}
    for path,entry in source_map.items():
        node=tree;parts=path.split('.')
        for part in parts[:-1]:node=node.setdefault(part,{})
        node[parts[-1]]=entry
    packet={'schema_version':VERSION,'context_sha256':digest(context),'sources':sources,'source_map':tree,'source_map_encoding':'nested_field_tree/v1','checks':checks,'comparisons':comparisons,'omissions':omissions,'unknown_policy':deepcopy(UNKNOWN_POLICY),'automatic_approval':False}
    packet['packet_sha256']=digest(packet)
    return packet

def _compress_sources(sources):
    # Lossless substring reuse, not summarization. Only strictly shorter source
    # strings may be referenced, so recursively resolving cannot introduce cycles.
    originals={sid:v for sid,v in sources.items() if isinstance(v,str)}
    for sid,value in originals.items():
        candidates=sorted(((k,v) for k,v in originals.items() if 48<=len(v)<len(value) and v in value),key=lambda item:-len(item[1]))
        if not candidates:continue
        segments=[];remaining=value
        while remaining:
            matches=[(remaining.find(v),k,v) for k,v in candidates if v in remaining]
            if not matches:segments.append(remaining);break
            pos,key,text=min(matches,key=lambda m:(m[0],-len(m[2])))
            if pos:segments.append(remaining[:pos])
            segments.append({'source_id':key});remaining=remaining[pos+len(text):]
        replacement={'$concat':segments}
        if len(json.dumps(replacement,ensure_ascii=False))<len(json.dumps(value,ensure_ascii=False)):sources[sid]=replacement

def source_value(packet,sid,_visiting=None):
    visiting=set() if _visiting is None else _visiting
    if sid in visiting:_error('cyclic source reference')
    if sid not in packet['sources']:_error('unknown source reference')
    value=packet['sources'][sid]
    if isinstance(value,dict) and set(value)=={'$concat'}:
        visiting=visiting|{sid}
        return ''.join(segment if isinstance(segment,str) else str(source_value(packet,segment['source_id'],visiting)) for segment in value['$concat'])
    return value

def iter_source_map(packet):
    """Yield actual dotted source paths and IDs from the compact field tree."""
    yield from _leaves(packet['source_map'])

def _flat_map(packet):
    return dict(iter_source_map(packet))

def _packet(value):
    if isinstance(value,dict) and value.get('schema_version')==VERSION:
        if value.get('packet_sha256')!=digest({k:v for k,v in value.items() if k!='packet_sha256'}):_error('packet hash mismatch')
        return value
    return build_packet(value)

def build_prompt(packet_or_context):
    _packet(packet_or_context)
    return '''你是独立文字内容审核员。输入是程序从真实稿件绑定的证据包；source_map按原字段的嵌套路径（数组下标为字符串键）映射到sources中的完整原文，相同值只存一次。sources里的{$concat:[原文片段,{source_id:另一个ID}]}按顺序无损拼接，还原完整原文，不能忽略引用片段。checks列出必须逐项判断的检查，不是通过结论。不要声称实际视频、声音或口型通过。
只返回JSON：schema='focused_semantic_review/v1', context_sha256照抄包值, checks数组, issues数组, suggestions数组, calibration_focus数组, pending数组。
每个checks项恰为{check_id,status:'passed'|'failed'|'unknown',reason,issue_ids:[],unknown:null或{reason_code,missing_evidence:[],owner_stage,action}}。覆盖包中每个check_id且只一次；不得空issues代替检查。failed必须关联issues，passed/unknown不能关联问题；unknown说明缺什么、由谁如何解决。未知不能改为passed或审美建议。
issues采用{id,owner:'writer'|'director',location:已有镜号,severity:'blocking'|'major',rule,evidence,contradiction,impact,proposal,evidence_ids:[]}。证据ID必须来自本包，至少一项属于真实script/shots/production_design正文。建议采用{location,proposal,reason}。pending仅用于非必需审美或后续实际媒体检查，结构同unknown并增加scope:'advisory'|'media'；不能把当前关键语义缺口放入pending。
检查职责：requirements对照简报与完整故事核对人物关系、转折、结尾和叙事作用；timing核对刺激、动作完成、反应保持、回应及切点顺序；continuity对照操作与全部表演原文、相邻首末态、位置朝向持物和空间前提；dialogue_timing核对台词及排时，合法同步动作不得串行累加；first_frame核对动作前状态并比较最终prompt是否擅自提前动作；assets核对身份、场景、布局及复用条件，不声称实际素材已通过。
comparisons是必须读的对照：操作—文字（特别dialogue_performance和groups.performance是否新增未记录动作）；上镜末—下镜首；切点—未完成对白与叙事任务（camera不能暗含第二个切点）。原计划、派生状态与最终prompt有冲突时报告，不能以程序生成就认定正确。状态保持从目标动作完成后开始。坐下核对可坐侧、移动和朝向，不只检查站立→坐下。
只把有证据的硬约束/叙事/物理错误列failed；明确相互矛盾的需求用REQUIREMENT_CONFLICT，合法剧情当前协议不能表达用EXPRESSION_UNSUPPORTED，不能要求改剧情迁就Schema。不能确定关键语义用unknown（默认需复核），不靠关键词新增禁令。正确反例与合理同步动作应按实际来源判断。
unknown reason_code:来源/必需证据缺失SOURCE_MISSING/REQUIRED_EVIDENCE_MISSING、必需检查未执行CHECKER_NOT_EXECUTED、要求冲突REQUIREMENT_CONFLICT、协议不支持EXPRESSION_UNSUPPORTED均阻断；其他关键语义未知需复核。pending仅允许OPTIONAL_AESTHETIC或ACTUAL_MEDIA_AUDIO_PENDING/ACTUAL_MEDIA_LIPSYNC_PENDING/ACTUAL_MEDIA_VISUAL_PENDING。'''

def unknown_disposition(value,*,required=True):
    reason=value.get('reason_code') if isinstance(value,dict) else None
    if isinstance(reason,str): reason=reason.strip().upper()
    if reason in BLOCKED_REASONS:return 'blocked'
    if not required and reason in ADVISORY_REASONS and value.get('scope') in ('advisory','media'):return 'advisory_pending'
    return 'review_required'

def _validate_unknown(value):
    if not isinstance(value,dict):_error('unknown needs disposition record')
    for key in ('reason_code','owner_stage','action'):_text(value.get(key),'unknown.'+key)
    if not isinstance(value.get('missing_evidence'),list) or not value['missing_evidence']:_error('unknown.missing_evidence must explain missing evidence')
    for item in value['missing_evidence']:_text(item,'missing_evidence item')

def _expanded_refs(ids,packet,prefixes=None):
    if not isinstance(ids,list) or not ids or any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):_error('evidence_ids must be nonempty unique strings')
    refs=[]
    for sid in ids:
        if sid not in packet['sources']:_error('unknown evidence ID: '+sid)
        value=source_value(packet,sid)
        if not ((isinstance(value,str) and value.strip()) or type(value) in (int,float)):continue
        quote=value if isinstance(value,str) else json.dumps(value)
        refs.extend({'path':p,'quote':quote} for p,entry in _flat_map(packet).items() if entry==sid and (prefixes is None or any(p==pre or p.startswith(pre+'.') for pre in prefixes)))
    return refs

def validate_review(raw,packet_or_context):
    packet=_packet(packet_or_context)
    if not isinstance(raw,dict) or set(raw)!={'schema','context_sha256','checks','issues','suggestions','calibration_focus','pending'}:_error('review fields incomplete or unknown')
    if raw['schema']!=REVIEW_SCHEMA or raw['context_sha256']!=packet['context_sha256']:_error('stale review schema/context hash')
    for key in ('checks','issues','suggestions','calibration_focus','pending'):
        if not isinstance(raw[key],list):_error(key+' must be array')
    expected={c['check_id']:c for c in packet['checks']}
    if any(not isinstance(c,dict) or not isinstance(c.get('check_id'),str) for c in raw['checks']):_error('invalid check')
    ids=[c['check_id'] for c in raw['checks']]
    if len(ids)!=len(expected) or set(ids)!=set(expected):_error('all required checks must be explicitly covered once')
    issues={};locations={c['location'] for c in packet['checks']}
    for issue in raw['issues']:
        if not isinstance(issue,dict):_error('issue must be object')
        for key in ('id','rule','evidence','contradiction','impact','proposal'):_text(issue.get(key),'issue.'+key)
        if issue['id'] in issues or issue.get('owner') not in ('writer','director') or issue.get('severity') not in ('blocking','major') or issue.get('location') not in locations:_error('invalid issue identity/owner/severity/location')
        refs=_expanded_refs(issue.get('evidence_ids'),packet)
        if not any(r['path'].split('.')[0] in ('script','shots','production_design') for r in refs):_error('issue lacks actual creative body evidence')
        issues[issue['id']]=issue
    linked=set()
    for check in raw['checks']:
        if set(check)!={'check_id','status','reason','issue_ids','unknown'}:_error('check fields incomplete')
        _text(check['reason'],'check.reason')
        if check['status'] not in ('passed','failed','unknown'):_error('invalid check status')
        links=check['issue_ids']
        if not isinstance(links,list) or any(not isinstance(i,str) or i not in issues for i in links):_error('unknown issue link')
        if (check['status']=='failed')!=bool(links):_error('failed needs issue; passed/unknown cannot hide known failure')
        if any(issues[i]['location']!=expected[check['check_id']]['location'] for i in links):_error('issue linked to different shot')
        linked.update(links)
        if check['status']=='unknown':_validate_unknown(check['unknown'])
        elif check['unknown'] is not None:_error('only unknown may carry unresolved evidence')
    if linked!=set(issues):_error('every issue needs failed check')
    for suggestion in raw['suggestions']:
        if not isinstance(suggestion,dict):_error('invalid suggestion')
        for key in ('location','proposal','reason'):_text(suggestion.get(key),'suggestion.'+key)
    for focus in raw['calibration_focus']:_text(focus,'calibration_focus item')
    for pending in raw['pending']:
        _validate_unknown(pending)
        if unknown_disposition(pending,required=False)!='advisory_pending':_error('pending cannot hide required unresolved checks')

def review_disposition(raw,packet_or_context):
    validate_review(raw,packet_or_context)
    unknowns=[{'check_id':c['check_id'],**deepcopy(c['unknown']),'disposition':unknown_disposition(c['unknown'])} for c in raw['checks'] if c['status']=='unknown']
    failures=[c['check_id'] for c in raw['checks'] if c['status']=='failed']
    disposition='blocked' if any(u['disposition']=='blocked' for u in unknowns) else 'review_required' if unknowns else 'failed' if failures else 'advisory_pending' if raw['pending'] else 'passed'
    return {'disposition':disposition,'can_handoff':not unknowns and not failures,'requires_resolution':bool(unknowns),'unknowns':unknowns,'known_failures':failures,'pending':deepcopy(raw['pending']),'automatic_approval':False}

def to_legacy_review(raw,context):
    """Expand bound sources, never invent judgments; assistant gate remains required."""
    packet=build_packet(context);disposition=review_disposition(raw,packet)
    if disposition['requires_resolution']:_error('unknown blocks legacy approval: '+disposition['disposition'])
    issues=[]
    for issue in raw['issues']:
        expanded={k:deepcopy(v) for k,v in issue.items() if k!='evidence_ids'}
        expanded['evidence_refs']=_expanded_refs(issue['evidence_ids'],packet);issues.append(expanded)
    coverage=[];results={c['check_id']:c for c in raw['checks']}
    for definition in packet['checks']:
        location=definition['location'];prefixes=definition['source_prefixes']
        if not coverage or coverage[-1]['id']!=location:coverage.append({'id':location,'checks':{}})
        result=results[definition['check_id']]
        source_ids=list(dict.fromkeys(sid for path,sid in _flat_map(packet).items() if any(path==pre or path.startswith(pre+'.') for pre in prefixes)))
        coverage[-1]['checks'][definition['kind']]={'status':'pass' if result['status']=='passed' else 'fail','reason':result['reason'],'issue_ids':deepcopy(result['issue_ids']),'evidence_refs':_expanded_refs(source_ids,packet,prefixes)}
    legacy={'story_preserved':not issues,'issues':issues,'suggestions':deepcopy(raw['suggestions']),'calibration_focus':deepcopy(raw['calibration_focus'])+['待验（非passed）: '+p['reason_code']+': '+p['action'] for p in raw['pending']],'coverage':coverage}
    from .creative_review_gate import validate_review as validate_legacy
    validate_legacy(legacy,context)
    return legacy

expand_review=to_legacy_review

def packet_diff(context,packet=None):
    packet=packet or build_packet(context)
    if packet['context_sha256']!=digest(context):_error('stale packet source')
    original=dict(_leaves(context));preserved=[p for p in original if p in _flat_map(packet)]
    for path in preserved:
        if source_value(packet,_flat_map(packet)[path])!=original[path]:_error('source value mismatch: '+path)
    semantic=[p for p in original if p.startswith(('state_plan.','shots.'))];missing=sorted(set(semantic)-set(preserved))
    return {'schema_version':'review_packet_diff/v1','context_sha256':digest(context),'preserved_leaf_count':len(preserved),'original_leaf_count':len(original),'semantic_leaf_count':len(semantic),'missing_semantic_paths':missing,'semantic_coverage':(len(semantic)-len(missing))/len(semantic) if semantic else 0,'omissions':deepcopy(packet['omissions']),'context_json_characters':len(json.dumps(context,ensure_ascii=False)),'packet_json_characters':len(json.dumps(packet,ensure_ascii=False)),'character_counts_are_not_tokens':True,'automatic_approval':False}

REVIEW_PACKET_SCHEMA = {
    '$schema':'https://json-schema.org/draft/2020-12/schema',
    '$id':'urn:ai-douyin:focused-review-packet:v1',
    'type':'object',
    'required':['schema_version','context_sha256','packet_sha256','sources','source_map','source_map_encoding','checks','comparisons','omissions','unknown_policy','automatic_approval'],
    'additionalProperties':False,
    'properties':{
        'schema_version':{'const':VERSION},
        'context_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},
        'packet_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},
        'sources':{'type':'object','minProperties':1,'patternProperties':{'^E[0-9]+$':{'anyOf':[{'type':['string','number','boolean','null']},{'type':'object','required':['$concat'],'additionalProperties':False,'properties':{'$concat':{'type':'array','minItems':1,'items':{'anyOf':[{'type':'string'},{'type':'object','required':['source_id'],'additionalProperties':False,'properties':{'source_id':{'type':'string','pattern':'^E[0-9]+$'}}}]}}}}]}},'additionalProperties':False},
        'source_map':{'$ref':'#/$defs/field_tree'},
        'source_map_encoding':{'const':'nested_field_tree/v1'},
        'checks':{'type':'array','minItems':1,'items':{'type':'object','required':['check_id','location','kind','required','source_prefixes'],'additionalProperties':False,'properties':{'check_id':{'type':'string'},'location':{'type':'string'},'kind':{'enum':list(CHECKS)},'required':{'const':True},'source_prefixes':{'type':'array','items':{'type':'string'},'minItems':1}}}},
        'comparisons':{'type':'array','minItems':3,'items':{'type':'object','required':['kind','location','left','right'],'additionalProperties':False,'properties':{'kind':{'enum':['operations_vs_prose','end_vs_next_start','cut_vs_unfinished_tasks']},'location':{'type':'string'},'left':{'type':'array','items':{'type':'string'}},'right':{'type':'array','items':{'type':'string'}}}}},
        'omissions':{'type':'array'},'unknown_policy':{'type':'object'},'automatic_approval':{'const':False}},
    '$defs':{'field_tree':{'type':'object','additionalProperties':{'anyOf':[{'type':'string','pattern':'^E[0-9]+$'},{'$ref':'#/$defs/field_tree'}]}}}}


def export_packet_artifacts(context, directory):
    """Offline, immutable artifacts. Does not call a model or mark review passed."""
    from datetime import datetime, timezone
    from pathlib import Path
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    packet=build_packet(context)
    metadata={'schema_version':VERSION,'source_hash':digest(context),'created_at':datetime.now(timezone.utc).isoformat(),'implementation_status':'implemented_offline_verified_not_production_verified'}
    artifacts={
        'review_packet.schema.json':{**REVIEW_PACKET_SCHEMA,**metadata},
        'packet_source_map.json':{**metadata,'source_map_encoding':packet['source_map_encoding'],'source_map':packet['source_map'],'sources':packet['sources'],'packet_sha256':packet['packet_sha256']},
        'packet_diff.json':{**metadata,**packet_diff(context,packet)},
        'unknown_policy.json':{**metadata,**UNKNOWN_POLICY},
        'review_packet.json':packet}
    result={}
    for filename,value in artifacts.items():
        path=root/filename
        if path.exists():
            prior=json.loads(path.read_text(encoding='utf-8'))
            # Creation timestamps are audit metadata, not a reason to overwrite.
            if {k:v for k,v in prior.items() if k!='created_at'}!={k:v for k,v in value.items() if k!='created_at'}:_error('artifact exists with different content: '+str(path))
        else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        result[filename]={'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    return result
