"""Two episode repair rounds with invalidated, freshly rebuilt continuity."""
import argparse,hashlib,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import contracts as c,prose_patch,revision_handoff as h
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger,NativeClient
from scripts.produce_serial_prose import SerialLedger
from src.content_factory.serial_story_runtime_v2 import run_lock

def plans(text,n):
    issues=[]
    def add(quote,reason):issues.append({'quote':quote,'reason':reason})
    def section(start,end,reason):
        a=text.index(start);b=text.index(end,a) if end else len(text)
        add(text[a:b],reason)
    if n==1:
        section('### 场3','### 场4','厨房内只有苏墨叶东叶南；其他孩子在另一间屋子。保留原文对话，明确厨房内/门外及兄弟离开去找其他孩子，不将群体全部列在厨房。')
        add('**苏墨（心声）**：可现在，那只被黑道大哥打瞎的眼睛还好好的。也就是说，还没到不可挽回的时候。',
            '此时仍闭眼，不能先知道眼睛完好。此处只表达对穿书结局的担忧；后面的睁眼观察和松口气原样保留。')
    else:
        add(text.splitlines()[0],'这是连载第7集，小说来源为第13章，不把章号当集号。')
        add('【场一】傍晚','【场一】时间在救人翌日、赴宴当天的下班前；明确同日关系，不具体虚构钟点。')
        add('【场二】傍晚','同场一，赴宴当天的下班前。')
        add('【场三】夜','回家重聚在当日邀请苏墨、下班赴宴之前。')
        add('赵雪（40上下，眉眼疲惫）','未有核准年龄，保留表情删去具体岁数。')
        add('余幼薇（十八九岁，短发，及膝白裙改成日常穿的旧衬衫）','未有核准年龄，描述当前衣着即可，不写把裙子改成衬衫。')
        add('余正华坐在客厅沙发上，四十多岁，鬓角微白，虽然一身便装，眉宇间仍压得住场面。','未有核准年龄，删去具体年龄，保留不影响事件的表演外观。')
        section('赵雪声音发涩：','余正华沉声：','用原文赵雪将昨晚经过告诉丈夫表达，简洁拍摄动作或有据对白即可；保留苏墨相救，不新编楼下/楼道经历，不重复讲述。')
        section('【场四】','【场五】','邀请在相救翌日、下班赴宴前，与前三场同日。原文未明确接电话地点，不伪造夜里在家再隔天赴宴。保留接电话想起原书没救人而余正华也翻身的内心，不新增事实。')
        add('【场五】次日傍晚','改为同日下班后，接到邀请的当天。')
        add('【场六】次日傍晚','改为同日晚饭前，接到邀请的当天。')
        add('叶东（十五六岁，个子最高，手里端着盘子）','叶东11岁，有第5/9/28章原文证据；保留端菜动作。')
        add('叶南（十三四岁）','叶南精确年龄暂未确认，删除具体岁数，保留名字。')
        add('进门，他先掏出家里那部备用手机——他赴宴前给它发过信息，通知孩子们他晚些回来。',
            '家中手机在家留给孩子收消息；不写苏墨从口袋掏出这部接收手机。回家动作和事前发消息的事实分开。')
        section('【场十】',None,'赴宴翌日新闻开始打击赌博；后续收集证据是逐步进行，不全塞同一瞬间。不新增已停职、通知纪检等结果，不新增孩子得知父亲救人及卷入棋局剧情。用原文13章末的新闻/调查进展作结，可旁白，保留事实而非凭空对白。')
    return prose_patch.prepare(text,issues)

def prepare(run,prior):
    old=read(prior/'STATE.json');plan=read(prior/'PLAN.json');source=read(prior/'SOURCE.json');registry=read(prior/'REGISTRY.json')
    if old['pending'] is not None or old['status'] in ('prepared','running','outcome_unknown'):raise ValueError('unsettled')
    run.mkdir(exist_ok=False);cat=c.catalog(source)
    inventory=[p for p in cat.values() if re.search('岁|年龄|年纪',p['text'])]
    for row in registry['characters']:
        if row['id']=='dong':row['age']={'text':'11岁','source_id':'CH5-P037'};row['source_ids']+=['CH5-P035','CH5-P037','CH9-P029','CH28-P015']
    registry['provenance']='主助手核对人物子集；全69章年龄关键词检索，非全书自动语义提取。叶东11岁跨章明确；其他年龄需区分近似、当前与原书未来。'
    plan.update(version='revision_handoff_two_rounds',max_calls=old['calls_started']+8,baseline_calls=old['calls_started'],baseline_tokens=old['reported_tokens'])
    plan['inference']={**plan['inference'],'writer_max_tokens':16384}
    paths=[__file__,'src/content_factory/novel_adaptation/revision_handoff.py','src/content_factory/novel_adaptation/prose_patch.py','src/content_factory/novel_adaptation/protocol_direct.py','scripts/produce_serial_prose.py']
    plan['implementation_pin']={str(Path(p).resolve()):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    for name,value in [('SOURCE',source),('REGISTRY',registry),('AGE_SOURCE_INVENTORY',inventory),('PLAN',plan),
        ('AUTHORIZATION',{'user_statement':'推两轮试试','scope':'episode1 then7 scoped MiniMax prose repair, fresh continuity and advisory review; no media',
        'planned_calls':6,'max_calls':8,'prior_state_sha256':digest(old),'prior':str(prior),'whole_book_understanding_claimed':False})]:freeze(run/(name+'.json'),value)
    for n in (1,7):
        draft=read(prior/f'CANDIDATE_{n:02}.json');freeze(run/f'ORIGINAL_{n:02}.json',draft)
        freeze(run/f'PATCH_PLAN_{n:02}.json',plans(draft['screenplay'],n))
    state={**old,'status':'prepared','pending':None,'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'rounds_completed':0}
    DirectLedger(run,plan,state,None).save()

def execute(run):
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json')
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('not_fresh')
        for p,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=sha:raise ValueError('changed_code')
        source=read(run/'SOURCE.json');registry=read(run/'REGISTRY.json');indexed=c.indexed_chapters(source)
        ledger=SerialLedger(run,plan,state,NativeClient(run,plan))
        try:
            for n,chapters in [(1,[1,2]),(7,[12,13])]:
                original=read(run/f'ORIGINAL_{n:02}.json');pp=read(run/f'PATCH_PLAN_{n:02}.json')
                base={'complete_source_chapters':[x for x in indexed if x['index'] in chapters],'registry':registry,
                    'cross_chapter_age_evidence':read(run/'AGE_SOURCE_INVENTORY.json')}
                edits=ledger.call(f'PATCH_{n:02}','writer',
                    '按明确核对的问题修改指定原样跨度，工具参数每个edit键对应替换文本，键外正文由程序原样保留。'
                    '任务是小说影视改编，可写自然动作表情镜头，保持事件/时间/人物事实和条件猜测的性质。'
                    '人物资料只允许明确来源年龄，近似保持近似。原文有些事实在后章才说明，年龄证据已附。'
                    '输出只包含替换文本，不解释，不重写整集，不生成continuity。保留场标题、相邻衔接及未改文本成立。',
                    {**base,'complete_screenplay':original['screenplay'],'fixed_spans':pp},prose_patch.schema(pp))
                revised=h.revise(original,pp,edits,source,registry)
                freeze(run/f'REVISED_{n:02}.json',revised)
                (run/f'第{n}集_两轮试验修订稿_待验收.md').write_text(revised['screenplay'],encoding='utf-8')
                rebuilt=ledger.call(f'REBUILD_{n:02}','writer',
                    '根据修后的完整正文与原文，重新生成供后集使用的承接资料。没有旧摘要可沿用。'
                    '明确当前结束时间、人物位置、已发生事件、知情范围、尚未发生/待解决事项。'
                    '已核人物资料优先；若正文和原文矛盾，在summary中标冲突待审，不把错误当事实。'
                    '不新增剧情，不推演结果，控制1000汉字以内，原文未来与当前分开。',
                    {**base,'candidate':revised},c.obj(summary=c.TEXT))
                handoff=h.attach(revised,rebuilt['summary'],source,registry);freeze(run/f'HANDOFF_{n:02}.json',handoff)
                audit=ledger.call(f'AUDIT_{n:02}','writer',
                    '审核完整正文和新承接是否与原文/人物资料一致。只列真实矛盾及精确原句依据；合理表演与未逐字复制不是错误。'
                    '核对全部场次在场/时间/知情关系及已发生和未发生区别，检查任何漏修或新错误。'
                    '年龄跨章证据已附，不能因本章未写就判全书无据。不要给肯定性补充事实。'
                    '报告1500汉字以内：通过/不通过/不确定、各问题候选引文+原文编号+理由。审核仅建议，无自动放行。',
                    {**base,'candidate':revised,'rebuilt_handoff':handoff},c.obj(review=c.TEXT))
                freeze(run/f'REVIEW_BINDING_{n:02}.json',{'candidate_sha256':digest(revised),'handoff_sha256':digest(handoff),'result':audit})
                (run/f'第{n}集_模型复核.md').write_text(audit['review'],encoding='utf-8')
                state['rounds_completed']+=1;ledger.save()
            state['status']='awaiting_primary_review'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:2500]})
        finally:ledger.save()

def prepare_focused(run,prior):
    from src.content_factory.novel_adaptation import context_projection as projection
    old=read(prior/'STATE.json');plan=read(prior/'PLAN.json');source=read(prior/'SOURCE.json');cat=c.catalog(source)
    if old['pending'] is not None or old['status'] in ('prepared','running','outcome_unknown'):raise ValueError('unsettled')
    run.mkdir(exist_ok=False)
    rounds=[]
    for name,previous_chapters,target_chapter,end_phrase,goal,needs in [
        ('dinner',[1,2],3,'他现在在主角们心中的印象',
         '接饭桌上的辍学争论，写到孩子回屋、苏墨困惑为止；保持当天饭后连续场景。',
         ['当前争论起因','人物与在场承接','孩子误解与苏墨的知情边界']),
        ('door',[12,13],14,'还能听到周红秋在外面骂人的声音',
         '苏墨回家遇周红秋与六孩子在门口对峙，写到关门为止；原文未明说具体日期钟点，保持未指定。',
         ['与本场有关的家庭关系和既有矛盾','孩子与苏墨关系的当前变化','本段所需时间地点承接'])]:
        end=[p for p in cat.values() if p['chapter']==target_chapter and end_phrase in p['text']]
        if len(end)!=1:raise ValueError('target_boundary_not_unique')
        end_num=int(end[0]['id'].split('P')[-1])
        target=[k for k,v in cat.items() if v['chapter']==target_chapter and int(k.split('P')[-1])<=end_num]
        allowed=[k for k,v in cat.items() if v['chapter'] in previous_chapters]
        spec={'id':name,'previous_chapters':previous_chapters,'goal':goal,'needs':needs,'prior_ids':allowed,'target_ids':target}
        rounds.append(spec)
        previous={'source_sha256':digest(source),'evidence':{k:cat[k] for k in allowed+['CH5-P037']},'history':[]}
        freeze(run/(name+'_PREVIOUS_INDEX.json'),previous)
    plan.update(version='focused_evidence_two_rounds',max_calls=old['calls_started']+6,
        baseline_calls=old['calls_started'],baseline_tokens=old['reported_tokens'])
    plan['inference']={**plan['inference'],'writer_max_tokens':16384}
    paths=[__file__,'src/content_factory/novel_adaptation/context_projection.py','src/content_factory/novel_adaptation/handoff.py',
           'src/content_factory/novel_adaptation/protocol_direct.py']
    plan['implementation_pin']={str(Path(p).resolve()):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    for name,value in [('PLAN',plan),('SOURCE',source),('FOCUSED_ROUNDS',rounds),
        ('AUTHORIZATION',{'user_statement':'那按这个改两轮','prior':str(prior),'prior_state_sha256':digest(old),
          'scope':'select relevant original evidence then generate two bounded next-scene probes from real novel; no summaries/media/publishing',
          'planned_calls':4,'max_calls':6,'unchanged_source_preserved':True,'not_whole_episode_repair':True})]:freeze(run/(name+'.json'),value)
    state={**old,'status':'prepared','pending':None,'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'rounds_completed':0}
    DirectLedger(run,plan,state,None).save()


def execute_focused(run):
    from src.content_factory.novel_adaptation import context_projection as projection,handoff
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json');source=read(run/'SOURCE.json');cat=c.catalog(source)
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('not_fresh')
        for path,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('changed_code')
        ledger=DirectLedger(run,plan,state,NativeClient(run,plan))
        try:
            for spec in read(run/'FOCUSED_ROUNDS.json'):
                name=spec['id'];target={k:cat[k] for k in spec['target_ids']}
                chosen=ledger.call('SELECT_'+name,'writer',
                    '只检索与给定下一段直接有关的前文原段编号。不要重写摘要或新增事实。'
                    '各need填必要原段ID，不相关的年龄、未来身份、支线、布景不要收集；信息不足可空数组，空不代表全书没有。'
                    '目标片段原文将另外完整提供给编剧，不要从前文重复收集目标已明说的事实。'
                    '选择应覆盖冲突起因、当前关系及必须避免泄露的知情界限；保留否定/条件/猜测原段。',
                    {'goal':spec['goal'],'needs':spec['needs'],'prior_material':{k:cat[k] for k in spec['prior_ids']},
                     'target_source_not_yet_enacted':target},projection.relevance_schema(spec['needs'],spec['prior_ids']))
                packet=projection.relevant_packet(source,spec['needs'],spec['prior_ids'],chosen,target_id=name)
                freeze(run/(name+'_PACKET.json'),packet)
                used_schema=c.refs(list(packet['evidence']),minimum=0) if packet['evidence'] else {'type':'array','maxItems':0,'items':{'type':'string'}}
                schema=c.obj(screenplay=c.TEXT,used_prior_ids=used_schema,enacted_target_ids=c.refs(spec['target_ids'],minimum=1))
                candidate=ledger.call('SCENE_'+name,'writer',
                    '只生成目标范围的连续短剧片段。输入只有按需原段和完整目标原文；角色动作、表情、环境与对白要清楚，信息及时推进。'
                    '保留人物说话归属、条件、否定、猜测和计划性质，不补具体年龄或未说明的日期，不把心声交给其他人知道。'
                    '写到目标结束位置就停；不复述整章，不输出承接摘要。原文事件不能被下个阶段情节替代。'
                    'screenplay写自然剧本文字；used_prior_ids只选实际用到的前文，enacted_target_ids只选本段已演出的原文段落。'
                    '这两个编号列表不改写内容，由程序保存原段；计划对白被演出不代表计划已经执行。',
                    {'goal':spec['goal'],'relevant_prior_packet':packet,'complete_target_source':target},schema)
                freeze(run/(name+'_CANDIDATE.json'),candidate)
                (run/(name+'_剧本片段_待验收.md')).write_text(candidate['screenplay'],encoding='utf-8')
                previous=read(run/(name+'_PREVIOUS_INDEX.json'))
                delta=handoff.stage_reference_delta(previous,source,packet,candidate,
                    {'used_source_ids':candidate['enacted_target_ids']},spec['target_ids'])
                freeze(run/(name+'_DELTA_PENDING.json'),delta)
                freeze(run/(name+'_METRICS.json'),{'prior_available_paragraphs':len(spec['prior_ids']),
                    'selected_paragraphs':len(packet['evidence']),'used_prior_ids':candidate['used_prior_ids'],
                    'prior_available_chars':sum(len(cat[k]['text']) for k in spec['prior_ids']),
                    'selected_chars':sum(len(x['text']) for x in packet['evidence'].values()),
                    'target_chars':sum(len(x['text']) for x in target.values()),'new_reference_count':len(delta['additions']),
                    'freeform_summary_generated':False,'state_semantics':'evidence index, not automatically proven world state'})
                state['rounds_completed']+=1;ledger.save()
            state['status']='awaiting_primary_focused_review'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:2500]})
        finally:ledger.save()


def prepare_questioned(run,prior):
    old=read(prior/'STATE.json');plan=read(prior/'PLAN.json');source=read(prior/'SOURCE.json');cat=c.catalog(source)
    if old['pending'] is not None or old['status'] in ('prepared','running','outcome_unknown'):raise ValueError('unsettled')
    run.mkdir(exist_ok=False)
    segments=[]
    for name,start,end in [('A',1,63),('B',65,115),('C',117,151)]:
        ids=[k for k,v in cat.items() if v['chapter']==20 and start<=int(k.split('P')[-1])<=end]
        segments.append({'id':name,'target_ids':ids,'before_id':ids[0]})
    evaluation={'frozen_before_calls':True,'not_sent_to_model':True,'route_holdout_only':'Chapter20 participated in old whole-book production, not current route tuning',
        'A':['叶寻担心大哥打架、请家长后苏墨再打人是猜测，不写成已发生。','夜里苏墨在隔壁，不能听见孩子未向他讲的私语。','次日七月周六不用上课，海鲜粥和饼；买衣服先宣布后出门。','六孩先出、苏墨最后关门。'],
        'B':['七人公交出行；六孩坐，苏墨站。','苏墨牵叶嫣儿与叶西决，四男孩走前面。','导购温柔像母亲不等于母亲出现。','嫣儿先选白裙试穿，苏墨为五个男孩选短袖并送试衣间。'],
        'C':['嫣儿穿白裙走出，后来五男孩也换新衣；无人物数量变化。','每个孩子三套不是总共三套。','送货上门须先留电话地址、配送前打电话确认时间；尚未送达。','最后全员穿新衣离店，不写送到家或进入下章吃饭。'],
        'common':['未核具体年龄不新增。','原文动作方向、主体、条件、计划性质不改。','装饰和镜头可改编但不当原文人物事实。']}
    continuation=plan.get('version')=='questioned_holdout_three_segments'
    baseline=plan['baseline_calls'] if continuation else old['calls_started']
    baseline_tokens=plan['baseline_tokens'] if continuation else old['reported_tokens']
    ceiling=plan['max_calls'] if continuation else old['calls_started']+12
    plan.update(version='questioned_holdout_three_segments',max_calls=ceiling,
        baseline_calls=baseline,baseline_tokens=baseline_tokens)
    plan['inference']={**plan['inference'],'writer_max_tokens':16384}
    paths=[__file__,'src/content_factory/novel_adaptation/question_retrieval.py',
           'src/content_factory/novel_adaptation/context_projection.py','src/content_factory/novel_adaptation/protocol_direct.py']
    plan['implementation_pin']={str(Path(p).resolve()):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    for name,value in [('PLAN',plan),('SOURCE',source),('SEGMENTS',segments),('EVALUATION_FROZEN',evaluation),
       ('AUTHORIZATION',{'user_statement':'可以（全书问题检索、3个未用于调参连续片段）','prior':str(prior),
        'prior_state_sha256':digest(old),'planned_calls':9,'max_calls':12,'scope':'text only; no media, publishing or default migration'})]:freeze(run/(name+'.json'),value)
    state={**old,'status':'prepared','pending':None,'baseline_calls':baseline,'baseline_tokens':baseline_tokens,'segments_completed':0}
    DirectLedger(run,plan,state,None).save()
    if continuation:
        import json
        from src.content_factory.novel_adaptation import question_retrieval as qr
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        n=old['calls_started'];call=read(prior/f'CALL_{n:03}.json');native=read(prior/f'RESPONSE_{n:03}.json')['native']
        if call['stage'].startswith('WRITE_'):
            if native['choices'][0]['finish_reason']!='tool_calls' or audit_folder(prior/f'native_{n:03}')['completion_evidence']!='known':raise ValueError('unknown_adoption')
            if digest(evaluation)!=digest(read(prior/'EVALUATION_FROZEN.json')):raise ValueError('evaluation_changed')
            failed_name=call['stage'].removeprefix('WRITE_')
            for spec in segments:
                name=spec['id']
                if name==failed_name:
                    candidate=read(prior/f'WRITE_{name}_DIRECT_DECODED.json')
                    original=json.loads(native['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
                    if candidate!=original:raise ValueError('native_candidate_changed')
                    freeze(run/f'{name}_CANDIDATE.json',candidate)
                    freeze(run/f'{name}_PACKET.json',read(prior/f'{name}_PACKET.json'))
                    freeze(run/f'{name}_METRICS.json',{'source_link_format_valid':False,'semantic_acceptance':False,'preserved_error':read(prior/'ERROR.json')})
                    freeze(run/f'COMPLETED_{name}.json',{'prior':str(prior),'native_result_sha256':digest(candidate),'native_sha256':digest(native),'generated_for_evaluation_only':True,'semantic_acceptance':False})
                elif (prior/f'COMPLETED_{name}.json').exists():
                    provenance=read(prior/f'COMPLETED_{name}.json')
                    candidate=read(prior/f'{name}_CANDIDATE.json')
                    if digest(candidate)!=provenance['native_result_sha256']:raise ValueError('copied_candidate_changed')
                    for tail in ['CANDIDATE','PACKET','METRICS']:freeze(run/f'{name}_{tail}.json',read(prior/f'{name}_{tail}.json'))
                    freeze(run/f'COMPLETED_{name}.json',provenance)
            return
        if not call['stage'].startswith('SELECT_QUESTIONS_') or native['choices'][0]['finish_reason']!='tool_calls':raise ValueError('unsupported_adoption')
        suffix=call['stage'].removeprefix('SELECT_QUESTIONS_')
        if audit_folder(prior/f'native_{n:03}')['completion_evidence']!='known':raise ValueError('unknown_adoption')
        questions=read(prior/f'QUESTIONS_{suffix}_DIRECT_DECODED.json')['questions'];searches=read(prior/f'{suffix}_SEARCHES.json')
        selections=json.loads(native['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
        targets=next(x['target_ids'] for x in segments if x['id']==suffix)
        qr.validate_selection(questions,searches,selections,targets)
        if digest(evaluation)!=digest(read(prior/'EVALUATION_FROZEN.json')):raise ValueError('evaluation_changed')
        freeze(run/f'{suffix}_KNOWN_ADOPTION.json',{'questions':questions,'searches':searches,'selection':selections,
            'native_sha256':digest(native),'prior':str(prior),'old_failure_preserved':True,'semantic_acceptance':False,
            'reason':'schema matches all visible prior/target evidence; target references deduplicated, unknown references withheld'})
        for spec in segments:
            name=spec['id']
            if (prior/f'{name}_CANDIDATE.json').exists() and (prior/f'{name}_METRICS.json').exists():
                values={tail:read(prior/f'{name}_{tail}.json') for tail in ['CANDIDATE','PACKET','METRICS']}
                native_value=read(prior/f'WRITE_{name}_DIRECT_DECODED.json')
                if values['CANDIDATE']!=native_value:raise ValueError('completed_candidate_changed')
                for tail,value in values.items():freeze(run/f'{name}_{tail}.json',value)
                (run/f'{name}_连续片段_待验收.md').write_text(native_value['screenplay'],encoding='utf-8')
                freeze(run/f'COMPLETED_{name}.json',{'prior':str(prior),'native_result_sha256':digest(native_value),
                    'artifacts':{tail:digest(value) for tail,value in values.items()},'semantic_acceptance':False})


def execute_questioned(run):
    from src.content_factory.novel_adaptation import question_retrieval as qr,context_projection as projection
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json');source=read(run/'SOURCE.json');index=qr.BookIndex(source)
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('not_fresh')
        for path,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('changed_code')
        ledger=DirectLedger(run,plan,state,NativeClient(run,plan))
        try:
            for spec in read(run/'SEGMENTS.json'):
                name=spec['id'];target={k:index.catalog[k] for k in spec['target_ids']}
                if (run/f'COMPLETED_{name}.json').exists():
                    state['segments_completed']+=1;ledger.save();continue
                pos=index.order[spec['before_id']];near=index.keys[max(0,pos-2):pos]
                boundary={k:index.catalog[k] for k in near}
                adoption=read(run/f'{name}_KNOWN_ADOPTION.json') if (run/f'{name}_KNOWN_ADOPTION.json').exists() else None
                questions=adoption['questions'] if adoption else ledger.call('QUESTIONS_'+name,'writer',
                    '阅读本段原文与直接上文，只提出为了正确改编本段仍须查询的具体问题。'
                    '每问绑定本段一个或多个原段ID，并给检索关键词。不要宽泛询问全部背景或人物知道的一切。'
                    '目标原文已经明说的，不再询问；不影响本段动作、对白、关系或连续性的信息不查。'
                    '通常0至3问足够，无缺口就返回questions空数组。此步只提问，不猜答案。',
                    {'target_source':target,'immediate_original_boundary':boundary},qr.question_schema(spec['target_ids']))['questions']
                ids=[q['id'] for q in questions]
                if len(ids)!=len(set(ids)):raise ValueError('duplicate_question_id')
                searches=adoption['searches'] if adoption else {q['id']:index.search(q['search_terms'],spec['before_id']) for q in questions}
                freeze(run/(name+'_SEARCHES.json'),searches)
                eligible=list(dict.fromkeys(k for v in searches.values() for k in v['eligible_context_ids']))
                if adoption:selection=adoption['selection']
                elif questions:
                    selection=ledger.call('SELECT_QUESTIONS_'+name,'writer',
                        '仅为每个具体问题选足以作答的原段编号，保留指代/否定/条件上下文。目标原文已回答的不再补前文。'
                        '证据不足填unknown，可以保留待核参考编号，但unknown不会送给编剧当答案；目标原文若已回答可选其ID，由程序去重。'
                        '不扩写背景、不猜事实。命中不等于相关，按本段需要筛选。'
                        '这是全书检索后的叙事位置之前候选；后文命中已隔离，不把以后事件当当前发生。',
                        {'questions':questions,'target_source':target,'earlier_evidence_candidates':{k:index.catalog[k] for k in eligible}},
                        qr.selection_schema(questions,searches,spec['target_ids']))
                    qr.validate_selection(questions,searches,selection,spec['target_ids'])
                else:selection={}
                selected=list(dict.fromkeys(k for value in selection.values() if value['status']=='supported' for k in value['evidence_ids'] if k not in target))
                context={k:index.catalog[k] for k in list(dict.fromkeys(near+selected))}
                writer_selection={k:({'status':'unknown','evidence_ids':[]} if v['status']=='unknown' else v) for k,v in selection.items()}
                freeze(run/(name+'_RAW_SELECTION.json'),selection)
                packet={'source_sha256':digest(source),'target_id':name,'questions':questions,'selection':writer_selection,
                    'evidence':context,'later_evidence_withheld':True,'unknown_is_not_nonexistence':True}
                freeze(run/(name+'_PACKET.json'),packet)
                allowed=list(dict.fromkeys(spec['target_ids']+list(context)))
                schema=c.obj(screenplay=c.TEXT,creative_choices=c.array(c.TEXT),
                    source_links=c.array(c.obj(source_id=c.choices(allowed),screenplay_quote=c.TEXT),1),
                    unresolved_questions=c.array(c.TEXT))
                candidate=ledger.call('WRITE_'+name,'writer',
                    '将完整目标原文改编为连续剧本片段，范围严格止于本段最后事件。人物动作、环境、神情与对白清楚，信息及时推进。'
                    '原文明确的人物、动作方向、先后、数量、说话归属与条件/猜测/计划性质属于事实，不得反转或新增结果。'
                    '凝视与回避、尚未与已经等不能作为同义润色。心声/旁白必须明确标注，未明确出声的思想不得变成当面对白。'
                    '表情、机位和一般布景可适度补足，放在creative_choices说明，不能扩展人物背景或事件。'
                    '仅本段未解决且确需处理的来源问题填unresolved_questions，没问题可空。'
                    'source_links把关键动作/台词的本稿原样短引文与原段ID相连；这不是另写承接摘要。'
                    '不强迫固定分钟数，不复述整章，不提前后续情节。',
                    {'complete_target_source':target,'question_based_context':packet},schema)
                qr.validate_links(candidate,set(allowed));freeze(run/(name+'_CANDIDATE.json'),candidate)
                (run/(name+'_连续片段_待验收.md')).write_text(candidate['screenplay'],encoding='utf-8')
                freeze(run/(name+'_METRICS.json'),{'questions':len(questions),'retrieved_earlier_candidates':len(eligible),
                    'selected_original_paragraphs':len(selected),'context_chars':sum(len(p['text']) for p in context.values()),
                    'target_chars':sum(len(p['text']) for p in target.values()),'prior_chapters_manually_selected':False,
                    'query_statuses':{k:v['status'] for k,v in selection.items()},'source_link_format_valid':True,
                    'semantic_acceptance':False,'evaluation_transmitted':False})
                state['segments_completed']+=1;ledger.save()
            state['status']='awaiting_primary_holdout_review'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:2500]})
        finally:ledger.save()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute','prepare-focused','execute-focused','prepare-questioned','execute-questioned']);p.add_argument('--run',type=Path,required=True);p.add_argument('--prior',type=Path);a=p.parse_args()
    if a.command=='prepare':prepare(a.run,a.prior)
    elif a.command=='execute':execute(a.run)
    elif a.command=='prepare-focused':prepare_focused(a.run,a.prior)
    elif a.command=='execute-focused':execute_focused(a.run)
    elif a.command=='prepare-questioned':prepare_questioned(a.run,a.prior)
    else:execute_questioned(a.run)
