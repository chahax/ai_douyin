"""Opt-in evidence addressing help; never supplies or changes review conclusions."""
from copy import deepcopy
import json
from .creative_workflow_contract import CreativeContractError

VERSION='leaf_catalog_v1'
FIELD='review_evidence_interface_version'
RULES='''证据寻址接口leaf_catalog_v1：只能沿输入真实JSON对象/数组寻址，不能把字符串内容重新当JSON解析。shots.shots.N.start_state/end_state/prompt/visible_performance都是完整字符串叶子，即使文本含{"C01":...}也只能引用该字段本身，quote复制字符串内的真实片段；禁止end_state.C01.posture等虚构路径。结构化细字段可引用state_plan.initial_state.C01.posture等实际存在的叶子，但首帧/镜内对照仍分别引用原shots字段。
下方目录只列合法路径，不替你判断证据支持结论；同组parent+leaf组成点分路径。目录为候选子集，原文中其他真实字符串/数字叶子也可引用。引用字符串须逐字片段，数字引用JSON数值文本。字符串不可下钻。
时间语义：状态变化在event.end时成立；“完成动作后保持N秒”必须从动作end算至下一破坏该状态的动作start，不能把到达/转头耗时算成已保持。reaction_window只是待审核声明，不证明正文真的留出保持时间。核对已有对白窗口与实际文字，不凭印象猜字数；允许阈值内自然语速，不将可选慢读当硬错误。'''


def enabled(context): return context.get(FIELD)==VERSION


def leaf_catalog(context):
    """Compact grouped paths, no repeated scene prose or thousands of operation leaves."""
    groups={}
    roots=('creative_brief','brief','script','shots','previous_shot','state_plan','production_design','static_visual_manifest')
    def walk(node,path):
        if isinstance(node,dict):
            for k,v in node.items():
                if isinstance(k,str) and '.' not in k:
                    walk(v,path+'.'+k if path else k)
        elif isinstance(node,list):
            for i,v in enumerate(node): walk(v,path+'.'+str(i))
        elif isinstance(node,str) or type(node) in (int,float):
            parent,_,leaf=path.rpartition('.')
            typ='str' if isinstance(node,str) else 'num'
            groups.setdefault(parent,{}).setdefault(typ,[]).append(leaf)
    for root in roots:
        if root not in context: continue
        value=context[root]
        if root=='state_plan' and isinstance(value,dict):
            # Show actual initial fields and timing/meaning leaves; operations remain in context.
            value=deepcopy(value)
            for beat in value.get('beats',[]):
                for event in beat.get('events',[]):
                    event.pop('operations',None);event.pop('changes',None)
        walk(value,root)
    return groups


def _ref_lists(value,path=''):
    if isinstance(value,dict):
        for key,child in value.items():
            child_path=path+'.'+key if path else key
            if key=='evidence_refs': yield child_path,child
            else: yield from _ref_lists(child,child_path)
    elif isinstance(value,list):
        for i,child in enumerate(value): yield from _ref_lists(child,path+'.'+str(i))


def reference_error(ref,context):
    if not isinstance(ref,dict) or not isinstance(ref.get('path'),str) or not isinstance(ref.get('quote'),str) or not ref['quote'].strip():
        return {'reason':'path和quote必须为非空字符串'}
    path=ref['path'];target=context;parts=path.split('.');traversed=[]
    for part in parts:
        if isinstance(target,str):
            return {'reason':'string_leaf_cannot_be_traversed','actual_leaf_path':'.'.join(traversed)}
        try:
            if isinstance(target,list):
                if not part.isdigit(): raise KeyError(part)
                target=target[int(part)]
            elif isinstance(target,dict): target=target[part]
            else: return {'reason':'scalar_leaf_cannot_be_traversed','actual_leaf_path':'.'.join(traversed)}
        except (KeyError,IndexError,TypeError): return {'reason':'path_not_found','existing_parent':'.'.join(traversed)}
        traversed.append(part)
    if isinstance(target,str):
        if ref['quote'] not in target: return {'reason':'quote_not_verbatim_substring'}
    elif type(target) in (int,float):
        if ref['quote']!=json.dumps(target): return {'reason':'numeric_quote_must_equal_json_number'}
    else: return {'reason':'path_must_address_string_or_number_leaf'}
    return None


def diagnostics(value,context):
    from .creative_review_v6 import evidence_gaps
    invalid=[];valid_view=deepcopy(value)
    # Remove invalid refs only in a diagnostic copy, never return a repaired review.
    for (location,refs),(copy_location,copy_refs) in zip(_ref_lists(value),_ref_lists(valid_view)):
        if not isinstance(refs,list):
            invalid.append({'reference_path':location,'reason':'evidence_refs_must_be_array'})
            continue
        keep=[]
        for index,ref in enumerate(refs):
            error=reference_error(ref,context)
            if error:
                invalid.append({'reference_path':location+'.'+str(index),'path':ref.get('path') if isinstance(ref,dict) else None,**error})
            else:keep.append(ref)
        copy_refs[:]=keep
    return {'invalid_references':invalid,'missing_comparisons':evidence_gaps(valid_view,context)}


def prompt_addendum(context):
    return '\n'+RULES+'\n候选合法叶子目录(parent路径→叶子名及类型)：'+json.dumps(leaf_catalog(context),ensure_ascii=False,separators=(',',':'))


def validate_evidence(value,context):
    errors=diagnostics(value,context)
    if errors['invalid_references'] or errors['missing_comparisons']:
        raise CreativeContractError('leaf_catalog_v1证据错误汇总: '+json.dumps(errors,ensure_ascii=False,separators=(',',':')))
