from novel_multiround_20261027 import *
source=read(BASE/'SOURCE.json');idx={p['id']:p['text'] for p in source}
definitions={
 'baseline_continued':[
  (53,'返修新增无依据的追求行为预设','原文只是有老婆所以不能追富婆的念头。修订稿新增“不能像追林薇薇那样”，把未发生的追求拿来作比较。初审I003修订要求夹带“像林薇薇那样追富婆”，裁决只确认核心遗漏而忽略夹带内容，反馈污染了返修。',['CH10-P001','CH10-P003']),
  (64,'为未明示对象补名','拿碗筷的命令在这句原文中没有明确指定苏墨；材料直接绑定苏墨，依据不足。应保留对象未明，不能凭上下文补确定主语。',['CH10-P049','CH10-P051'])],
 'fewshot_continued':[
  (27,'否定词遗漏导致条件反转','原文“再不还钱就要打断你哥的腿”被写成“再还钱就打断大哥的腿”。这条从初稿到复审通过都未修正。',['CH10-P107']),
  (22,'让座对象错误','材料写周红秋呵斥苏墨让座，原文紧接叶北准备起身、苏墨让叶北继续吃饭；不得将让座对象换为苏墨。',['CH10-P053','CH10-P057','CH10-P061','CH10-P063']),
  (8,'动作变换且混合当前行为与未来承诺','原文连连摆头，写成连连摆手；未来再买发夹又与当下动作合并为actual。',['CH9-P089','CH9-P091']),
  (1,'邻章材料进入目标章','第8章下班领取工资被纳入目标第9—10章材料，虽保留CH8引用但没有输出层区分，仅作上下文的范围约束未落实。',['CH8-P017','CH8-P019'])]
}
for arm,issues in definitions.items():
    run=BASE/arm;material=read(run/'FINAL_MATERIAL.json');entries=[]
    for n,kind,reason,refs in issues:entries.append({'fact_index_1based':n,'kind':kind,'statement':material['facts'][n-1]['statement'],'finding':reason,'evidence':[{'source_id':i,'quote':idx[i]} for i in refs]})
    dump(run/'PRIMARY_REVIEW.json',{'status':'needs_revision','reviewer':'primary_assistant','candidate_sha256':sha(material),'machine_status':read(run/'RESULT.json')['status'],'issues':entries,'no_manual_edit':True,'full_script_acceptance':False})
    text='模型原生材料（未通过人工独立语义复核）\n\n'+'\n\n'.join(f'{i:03}. [{f["mode"]}] {f["statement"]}\n来源：'+', '.join(f['source_ids']) for i,f in enumerate(material['facts'],1))
    (run/'READABLE_MATERIAL.md').write_text(text,encoding='utf-8')
receipts=[]
for p in sorted(BASE.glob('**/RESPONSE_1.json')):
    r=read(p);native=r['native'];u=native['usage']
    receipts.append({'path':str(p.relative_to(BASE)),'sha256':sha(r),'tokens':u['total_tokens'],'finish':native['choices'][0]['finish_reason']})
dump(BASE/'ACCEPTANCE.json',{'status':'needs_revision','calls':len(receipts),'reported_tokens':sum(r['tokens'] for r in receipts),'all_new_receipts_known':True,'receipts':receipts,'baseline':{'calls':8,'repairs':2,'facts_before':95,'facts_after':96,'machine_pass':True,'primary_pass':False},'fewshot':{'calls':5,'repairs':1,'facts_before':31,'facts_after':32,'machine_pass':True,'primary_pass':False},'optimizer':'LabeledFewShot, real compile with 3 labeled demos, no optimizer model calls; not instruction search','tests':11,'old_unknown_untouched':True,'no_media_or_publication':True})
dump(BASE/'baseline/STATUS_RECONCILIATION.json',{'state_json_preserved':True,'actual_calls':3,'actual_pending':None,'known_native_tokens':58032,'evidence':'../baseline_continued/RECONCILIATION.json','explanation':'旧STATE.json未成功替换，pending JUDGE_0为本地持久化残留；同一步已有完整原生回执，不是新的API未知。已知回执采用后继续，无重派。'})
print(json.dumps({'calls':len(receipts),'tokens':sum(r['tokens'] for r in receipts)}))
