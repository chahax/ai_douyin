"""Context-bound evidence IDs. Selection is mechanical, never an approval decision."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from .creative_workflow_contract import CreativeContractError

VERSION='evidence_ids_v1'
FIELD='review_evidence_interface_version'
HINT_FIELD='evidence_id_repair_hints_version'
HINT_VERSION='missing_source_candidates_v1'
ROOTS=('creative_brief','brief','script','shots','previous_shot','state_plan','scheduled_state_plan','scheduling_report','production_design','static_visual_manifest')


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def enabled(context):return context.get(FIELD)==VERSION


def build_evidence_catalog(context):
    # Interface marker is not evidence and caller/assistant contexts may omit it.
    source={k:v for k,v in context.items() if k not in (FIELD,HINT_FIELD)}
    context_hash=digest(source);entries={}
    def add(path,quote):
        key='E'+context_hash[:12]+'-'+str(len(entries)+1).zfill(4)
        entries[key]={'path':path,'quote':quote}
    def walk(node,path):
        if not isinstance(node,(dict,list)):
            leaf=path.rsplit('.',1)[-1]
            if leaf in ('id','beat_id','schema','style_option_id','selected_candidate_id','reuse_key'):
                return
            if path.startswith('state_plan.') and leaf not in ('posture','position','gaze','affect','holder','location','performance','action','start','end','text','meaning','value','facing','duration_seconds','script_slot','kind','hold_subject','anchor'):
                return
            if path.startswith('scheduled_state_plan.') and leaf not in ('start','end','performance','action','text'):
                return
        if isinstance(node,dict):
            for key in sorted(node):
                if not isinstance(key,str) or '.' in key: continue
                # These compiler duplicates remain in full context for reasoning.
                if key in ('screenplay_markdown','prompt'):continue
                walk(node[key],path+'.'+key if path else key)
        elif isinstance(node,list):
            for index,value in enumerate(node):walk(value,path+'.'+str(index))
        elif isinstance(node,str) and node.strip():
            # IDs select a complete source leaf; the transmitted directory contains
            # only a navigation excerpt. Full text remains in the original context.
            add(path,node)
        elif type(node) in (int,float):add(path,json.dumps(node))
    for root in ROOTS:
        if root=='static_visual_manifest' and source.get('shots',{}).get('style'):
            continue  # The style has the complete compiled identity and fixed geometry.
        if root in source:walk(source[root],root)
    return {'schema':VERSION,'context_sha256':context_hash,'entries':entries}


def _ref_lists(value,path=''):
    if isinstance(value,dict):
        for key,item in value.items():
            here=path+'.'+key if path else key
            if key=='evidence_refs':yield here,item
            else:yield from _ref_lists(item,here)
    elif isinstance(value,list):
        for index,item in enumerate(value):yield from _ref_lists(item,path+'.'+str(index))


def expand_review_ids(raw,context):
    catalog=build_evidence_catalog(context);result=deepcopy(raw);errors=[]
    for location,refs in _ref_lists(result):
        if not isinstance(refs,list):
            errors.append({'location':location,'error':'evidence_refs必须为数组'});continue
        replacements=[]
        for index,ref in enumerate(refs):
            if not isinstance(ref,dict) or set(ref)!={'ref_id'} or not isinstance(ref['ref_id'],str):
                errors.append({'location':location+'.'+str(index),'error':'仅允许{ref_id:目录ID}，不可混用path/quote'});continue
            if ref['ref_id'] not in catalog['entries']:
                errors.append({'location':location+'.'+str(index),'error':'unknown_or_stale_ref_id','ref_id':ref['ref_id']});continue
            replacements.append(deepcopy(catalog['entries'][ref['ref_id']]))
        refs[:]=replacements
    if errors:raise CreativeContractError('evidence_ids_v1引用错误: '+json.dumps(errors,ensure_ascii=False,separators=(',',':')))
    receipt={'schema':'creative_evidence_ids_expansion/v1','context_sha256':catalog['context_sha256'],
             'catalog_sha256':digest(catalog),'raw_review_sha256':digest(raw),'effective_review_sha256':digest(result),
             'effective_review':result,'automatic_approval':False}
    return result,receipt


def save_expansion(run_dir,stage,raw,context):
    effective,receipt=expand_review_ids(raw,context)
    path=Path(run_dir)/(stage+'__evidence_ids_expansion.json')
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8'))!=receipt:raise RuntimeError('证据ID展开回执已绑定不同原稿/上下文')
    else:path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return effective


def build_prompt(context,base):
    import re
    # Supersede only the transport representation; semantic requirements remain.
    base=re.sub(r'evidence_refs每项为.*?原创简报优先于候选擅自加入的实现。',
                'evidence_refs每项仅为{"ref_id":"目录中的完整ID"}。选择真实支持结论的证据ID，不输出path/quote。每条issue至少一条当前script/shots/production_design正文证据。原创简报优先于候选擅自加入的实现。',base,count=1)
    catalog=build_evidence_catalog(context)
    compact={}
    for key,row in catalog['entries'].items():
        parent,_,leaf=row['path'].rpartition('.')
        compact.setdefault(parent,{})[leaf]=[key,row['quote'][:64]]
    return base+'\n证据传输版本evidence_ids_v1：目录按真实父路径→叶子名:[ref_id,前64字符导航片段]分组。ID选择该完整叶子，程序展开引用该叶子完整原文；导航片段不是审核范围。仅选择ID；可多选以覆盖对照双方，同一ID可复用，不得猜ID。ID已绑定此完整上下文。目录导航片段不改写原文，完整context仍是判断依据；不能因片段未涵盖某句就断言原文缺失。不把目录、程序编译或reaction_window标记当通过证据。\n动作状态在event.end才成立，保持时间从完成到下一破坏条件动作start核算。\n证据目录：'+json.dumps(compact,ensure_ascii=False,separators=(',',':'))


def build_repair(problem,context,original,base_prompt):
    instruction=('只修复审核对象的evidence_refs ID选择，其他问题、结论、status、reason、issue_ids、建议逐字保留。'
                 '完整review_context仅提供一次；target_contract含同一上下文绑定的证据目录。返回完整审核对象，'
                 'evidence_refs每项仅{ref_id:目录ID}，不得返回path/quote或删除问题。不能支持原结论时保持原结论并停待人工。')
    payload={'validation_error':str(problem),'review_context':deepcopy(context),'invalid_review':deepcopy(original),
             'target_contract':build_prompt(context,base_prompt)}
    if context.get(HINT_FIELD)==HINT_VERSION:
        instruction+=' candidate_evidence只是可选来源导航，不证明原结论成立；逐项阅读真实原文后选择，不得机械填满或改变结论。'
        payload['candidate_evidence']=repair_candidates(original,context)
    return instruction,payload


def repair_candidates(raw,context):
    """Suggest at most three existing sources per missing requirement; never select."""
    from .creative_review_v6 import evidence_gaps
    catalog=build_evidence_catalog(context);entries=catalog['entries'];filtered=deepcopy(raw);invalid=[]
    for location,refs in _ref_lists(filtered):
        if not isinstance(refs,list):
            invalid.append({'location':location,'error':'evidence_refs_must_be_array'});continue
        valid=[]
        for index,ref in enumerate(refs):
            if not isinstance(ref,dict) or set(ref)!={'ref_id'} or not isinstance(ref.get('ref_id'),str) or ref['ref_id'] not in entries:
                invalid.append({'location':location+'.'+str(index),'error':'unknown_stale_or_malformed_reference','reference':deepcopy(ref)})
            else:valid.append(ref)
        refs[:]=valid
    expanded,_=expand_review_ids(filtered,context)
    suggestions=[]
    for gap in evidence_gaps(expanded,context):
        check_path=gap['check_path'];parts=check_path.split('.')
        shot_index=parts[1] if len(parts)>1 else ''
        for prefix in gap['missing_source_prefixes']:
            options=[(key,row['path']) for key,row in entries.items() if row['path'].startswith(prefix)]
            def rank(option):
                path=option[1];leaf=path.rsplit('.',1)[-1]
                order={'visible_performance':0,'performance':0,'action':0,'start_state':1,'end_state':2,'posture':3,'holder':4,'gaze':5,'position':6}
                beat_rank=0 if '.beats.'+shot_index+'.' in path else 1
                return (beat_rank,order.get(leaf,20),path)
            options.sort(key=rank)
            suggestions.append({'check_path':check_path,'missing_source_prefix':prefix,
                                'candidates':[{'ref_id':key,'path':path} for key,path in options[:3]]})
    return {'schema':HINT_VERSION,'unknown_or_invalid_references':invalid,'missing_comparisons':suggestions,
            'automatic_selection':False,'requires_reading_source_and_preserving_conclusions':True}
