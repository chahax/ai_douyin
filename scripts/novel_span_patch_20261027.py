"""Bounded source-backed clause edits; unselected characters cannot change."""
from novel_independent_review_20261027 import *
TRIAL=ROOT/'data/corpus_production_trials/20261027_span_patch'
class SpanEdit(Strict):
    target_id:str
    replacement_text:str=Field(min_length=1)
    source_ids:list[str]=Field(min_length=1)
class SpanEdits(Strict):edits:list[SpanEdit]
def targets(material,selected):
    result=[]
    for f in bind(material):
        cursor=0
        for c in clauses([f])[0]['clauses']:
            end=cursor+len(c['text'])
            if c['clause_id'] in selected:result.append({'target_id':c['clause_id'],'fact_id':f['id'],'start':cursor,'end':end,'original_text':c['text'],'fact_sha256':sha(f)})
            cursor=end
    if {t['target_id'] for t in result}!=set(selected):raise ValueError('target_missing')
    return result
def apply_spans(material,target_list,raw,source):
    v=SpanEdits.model_validate(raw).model_dump();edits=v['edits'];by={t['target_id']:t for t in target_list};known={p['id'] for p in source}
    if len(edits)!=len(by) or {e['target_id'] for e in edits}!=set(by):raise ValueError('edit_scope')
    facts=bind(material);out=json.loads(json.dumps(material));changes=[]
    for i,f in enumerate(facts):
        patches=sorted([(by[e['target_id']],e) for e in edits if by[e['target_id']]['fact_id']==f['id']],key=lambda x:x[0]['start']);cursor=0;pieces=[];refs=list(f['source_ids'])
        for t,e in patches:
            if t['fact_sha256']!=sha(f) or f['statement'][t['start']:t['end']]!=t['original_text']:raise ValueError('stale_target')
            if t['start']<cursor:raise ValueError('overlap')
            if not set(e['source_ids'])<=known:raise ValueError('unknown_source')
            if len(e['replacement_text'])>3*len(t['original_text'])+24:raise ValueError('span_expansion_requires_separate_proposal')
            pieces.extend([f['statement'][cursor:t['start']],e['replacement_text']]);cursor=t['end']
            refs.extend(x for x in e['source_ids'] if x not in refs)
            changes.append({'target':t,'edit':e})
        if patches:pieces.append(f['statement'][cursor:]);out['facts'][i]['statement']=''.join(pieces);out['facts'][i]['source_ids']=refs
    return out,changes
SPAN_PROMPT='''只精确改写指定target_id中的original_text片段，不能输出整条材料。完整候选与原章仅用于理解语境。为避免歧义，优先沿用原文对行为、态度及范围的准确措辞；不新增说话人、动作或内心。原句存在合理读法也可精确化，不必虚构错误理由。replacement_text将由程序原位替换，前后字句均不变，务必保持标点和衔接。每target一次，source_ids必须支持新片段。若需要大幅增写才能成立，不强行塞入本片段。'''
def main():
    if TRIAL.exists():raise ValueError('no_replay')
    parent=ROOT/'data/corpus_production_trials/20261027_independent_review';material=read(parent/'INITIAL.json');source=read(OUT/'SOURCE.json');ts=targets(material,['F014-C04'])
    TRIAL.mkdir();dump(TRIAL/'PLAN.json',{'historical_book_calls_started':134,'old_unknown_untouched':1,'authorization':'继续直到方向无意义或真实生产测试完成无问题；MiniMax文本调用不再逐轮询问','max_calls':5,'scope':'已知F014局部修复；前一轮整条失败保留，此处从失败前原生材料派生','candidate_sha256':sha(material),'source_sha256':sha(source),'targets':ts,'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    session=Session(TRIAL);session.save();status='needs_attention';error=None
    try:
        raw=session.call('PATCH',SPAN_PROMPT,{'complete_source':source,'candidate':bind(material),'targets':ts},SpanEdits);dump(TRIAL/'PATCH.json',raw)
        current,changes=apply_spans(material,ts,raw,source);dump(TRIAL/'CHANGES.json',changes);dump(TRIAL/'FINAL_MATERIAL.json',current)
        final=review_all('FINAL_REVIEW',current,source,session,TRIAL);dump(TRIAL/'FINAL_REVIEW.json',final)
        status='machine_pass_pending_primary' if all(x['decision']=='supported' for r in final['rows'] for x in r['findings']) else 'needs_revision'
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:700]
    session.save();dump(TRIAL/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'pending':session.pending,'error':error});print(json.dumps(read(TRIAL/'RESULT.json')),flush=True)
if __name__=='__main__':main()
