"""Write independent review without altering native outputs or previous failures."""
from framework_bench_20261027 import *
issues={
 'langgraph':[(8,'钱款动作反转','将高个男孩从叶东位置拿钱塞入自己口袋，写为把钱塞进叶东书包位置。',['CH7-P003','CH7-P005','CH7-P007','CH7-P035']),(20,'场景时间拼接','把学校门口兄妹关心叶东与苏墨在家进厨房拼成同一连续事件。',['CH7-P061','CH7-P063','CH7-P065','CH7-P111'])],
 'pydanticai':[(16,'钱款动作反转','把男孩拿走叶东的钱写成把纸币塞进叶东位置。',['CH7-P003','CH7-P005','CH7-P007','CH7-P035']),(27,'行进主客体反转','写赵伟下班后将苏墨带到巷子；原文是苏墨自行绕路，黑车跟随。',['CH8-P025','CH8-P027','CH8-P033'])],
 'crewai':[(15,'钱款动作反转','写成男孩将纸币塞进叶东口袋。',['CH7-P003','CH7-P005','CH7-P007','CH7-P035']),(16,'名字切词错误','把“张玉刚说完”中的副词“刚”并入姓名，称张玉也叫张玉刚。',['CH6-P105','CH7-P009'])],
 'dspy':[(15,'在场人物自相矛盾','同条既把叶西决列入学校在场四人，又说他未出门、在家获知。',['CH6-P095','CH7-P091','CH7-P095','CH7-P103'])],
 'autogen':[(4,'比较量变成已发生','“赶上自己上班五天了”是1000元与五天工资比较，不能推出已上班五天。',['CH6-P073','CH6-P075','CH6-P077']),(17,'新增动机','张玉说忘了监控，材料却写成“以忘了监控为由推脱”，未有足够原文支持故意推脱。',['CH6-P147','CH6-P149','CH6-P151'])]
}
rows=[]
catalog={p['id']:p['text'] for p in read(BASE/'SOURCE.json')}
for framework in ('langgraph','pydanticai','dspy','crewai','autogen'):
    original=BASE/framework;latest=BASE/(framework+'_continued') if (BASE/(framework+'_continued')).exists() else original
    result=read(original/'RESULT.json');native_results=[result]
    if latest!=original:native_results.append(read(latest/'RESULT.json'))
    reading=read(latest/'READING.json');verdicts=read(latest/'VERDICTS.json');review=[]
    for n,kind,reason,refs in issues[framework]:
        review.append({'fact_index_1based':n,'kind':kind,'original_statement':reading['facts'][n-1]['statement'],'finding':reason,'source':[{ 'id':i,'text':catalog[i]} for i in refs]})
    secondary=[]
    if framework=='dspy':secondary.append({'claim_id':'H3','finding':'标签正确，但理由把原书未来又称为旧事，时间层措辞混杂。'})
    if framework=='langgraph':secondary.append({'claim_id':'H5','finding':'理由的“他老爸定的规矩”错引CH8-P041，实际在CH6-P041；又由旧规矩推当前健在，证据不足。'})
    if framework in ('crewai','autogen'):secondary.append({'claim_id':'H5','finding':'拒绝“因父亲刚去世而哭”合理；进一步断言父亲仍在世/并未去世，比所引证据更强。'})
    reviewdoc={'reviewer':'primary_assistant','status':'needs_revision','reading_sha256':sha(reading),'verdicts_sha256':sha(verdicts),'label_matches':sum(x['matches'] for x in read(latest/'SCORE.json')),'label_total':6,'material_issues':review,'reason_issues':secondary,'scope':'逐条检查盲读材料与6条审核理由；不是完整剧本或视频验收'}
    dump(latest/'PRIMARY_REVIEW.json',reviewdoc)
    rows.append({'framework':framework,'calls':sum(r['calls'] for r in native_results),'tokens':sum(r['reported_tokens'] for r in native_results),'seconds':round(sum(r['elapsed_seconds'] for r in native_results),3),'facts':len(reading['facts']),'labels':'6/6','semantic_status':'needs_revision','original_count_guard_failure':latest!=original})
dump(BASE/'COMPARISON.json',{'rows':rows,'total_calls':sum(r['calls'] for r in rows),'reported_tokens':sum(r['tokens'] for r in rows),'all_new_pending_null':all(read(p/'STATE.json')['pending'] is None for p in BASE.iterdir() if p.is_dir()),'content_winner':None,'limitations':['一轮、同一模型、6条构造留出主张，非完整小说生产','共享原生工具传输和Pydantic校验，框架SDK未各自直连；SDK回调层usage为占位，真实用量只取native','DSPy未运行优化器；CrewAI/AutoGen没有多角色辩论','包装提示不同；并发与缓存影响耗时，不能归因于框架','三套原生材料超过30上限；仅新续测去除无依据上限，原失败和原始响应不改']})
print(json.dumps(read(BASE/'COMPARISON.json'),ensure_ascii=False))
