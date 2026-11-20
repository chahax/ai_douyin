"""Source-locked scene expression and scoped repair trial; no media/default migration."""
import argparse,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import contracts as c,prose_patch,fact_locked_scene as locked
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger,NativeClient
from src.content_factory.serial_story_runtime_v2 import run_lock

def review(value,source,**extra):
    return {'reviewer':'primary_assistant','artifact_sha256':digest(value),'source_sha256':digest(source),
            'verdict':'approved','open_issues':[],**extra}

def prepare(run,prior):
    old=read(prior/'STATE.json');plan=read(prior/'PLAN.json');source=read(prior/'SOURCE.json');cat=c.catalog(source)
    if old['pending'] is not None or old['status'] in ('prepared','running','outcome_unknown'):raise ValueError('prior_unsettled')
    def ref(ch,needle):
        rows=[k for k,v in cat.items() if v['chapter']==ch and needle in v['text']]
        if len(rows)!=1:raise ValueError('source_anchor_not_unique:'+needle)
        return rows[0]
    def evidence(ch,needle,whole=False):
        key=ref(ch,needle);text=cat[key]['text'];a=0 if whole else text.index(needle)
        return locked.source_span(source,key,a,len(text) if whole else a+len(needle))
    people=[]
    for key,name,rank,ch,needle in [('su','苏墨',None,1,'苏墨闭着眼睛'),('dong','叶东',1,1,'老大叶东'),
        ('nan','叶南',2,1,'老二叶南眼中'),('bei','叶北',3,1,'老三叶北和老四叶寻'),
        ('xun','叶寻',4,1,'老三叶北和老四叶寻'),('yan','叶嫣儿',5,1,'老五叶嫣儿'),
        ('six','叶西决',6,1,'老六叶西决疼得'),('zhao','赵雪',None,12,'赵雪和余幼薇也接到了电话'),
        ('youwei','余幼薇',None,12,'赵雪和余幼薇也接到了电话'),('zhenghua','余正华',None,13,'坐在客厅的余正华')]:
        age=None
        if key in ('bei','xun'):age={'text':'七八岁','source_id':ref(1,'老三叶北和老四叶寻')}
        if key=='six':age={'text':'六七岁的样子','source_id':ref(1,'递来面包的孩子很矮')}
        people.append({'id':key,'name':name,'rank':rank,'age':age,'source_ids':[ref(ch,needle)],
                       'age_scope':'opening description; unknown is not inferred from rank'})
    registry={'source_sha256':digest(source),'characters':people,'relationships':[
       {'from':'zhao','to':'youwei','relation':'母女','source_ids':[ref(12,'赵雪和余幼薇也接到了电话')]},
       {'from':'zhao','to':'zhenghua','relation':'夫妻','source_ids':[ref(13,'看着妻女'),ref(13,'赵雪把昨晚发生的事')]}],
       'provenance':'Primary-assistant curated and source-checked subset, not automatically extracted whole-book facts.'}
    def line(id,kind,speaker,listener,ch,needle,whole=False,styles=None):
        value={'id':id,'kind':kind,'speaker':speaker,'listener':listener,'evidence':evidence(ch,needle,whole)}
        if styles:value['styles']=styles
        return value
    def contract(id,cast,place,places,previous,lines):
        return {'id':id,'registry_sha256':digest(registry),'time_label':'当日','place_label':place,
            'places':places,'previous_locations':previous,
            'presence':{'place_id':places[0],'initial_locations':{},'transitions':[],'end_cast':cast},'lines':lines}
    s1=contract('episode1_opening',['su','nan','six'],'苏墨的房间',['room'],
        {'su':'room','nan':'room','six':'room'},[
          line('D1','dialogue','six','nan',1,'二哥，今天没偷到钱，怎么办呀？'),
          line('D2','dialogue','nan','six',1,'哥哥发传单挣了十块，先给你。'),
          line('D3','dialogue','six','nan',1,'不行，你没交上钱，他会打你的。')])
    s7=contract('episode7_report',['zhao','zhenghua','youwei'],'余正华家客厅',['home'],
        {'zhao':'home','zhenghua':'home','youwei':'home'},[
          line('A1','action','zhao','zhenghua',13,'赵雪把昨晚发生的事告诉给余正华。',whole=True)])
    cast=['dong','nan','bei','xun','yan','six']
    s55=contract('holdout55_tree',cast,'动物园树荫下，孩子们近景；苏墨在画外',['tree','path'],
        {**{x:'tree' for x in cast},'su':'path'},[
          line('D1','dialogue','bei','nan',55,'二哥，他这是在干嘛？'),
          line('D2','dialogue','nan','bei',55,'不知道。'),
          line('D3','dialogue','bei','nan',55,'他不会又要使什么坏心眼吧？',styles=['压低声音说']),
          line('D4','dialogue','nan','bei',55,'我觉得应该不会。'),
          line('N1','narration',None,None,55,'苏墨此时正忙着逮路人拍照，并不知道六个孩子心里的想法。',whole=True)])
    scenes=[s1,s7,s55];run.mkdir(exist_ok=False)
    previous=plan['max_calls'];plan.update(max_calls=old['calls_started']+6,baseline_calls=old['calls_started'],
        baseline_tokens=old['reported_tokens'],version='fact_locked_scene_trial_v1')
    plan['inference']={**plan['inference'],'writer_max_tokens':8192}
    plan['implementation_pin']={}
    import hashlib
    for path in ['scripts/run_fact_locked_revision.py','src/content_factory/novel_adaptation/fact_locked_scene.py',
                 'src/content_factory/novel_adaptation/prose_patch.py','src/content_factory/novel_adaptation/contracts.py']:
        plan['implementation_pin'][path]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    for name,value in [('PLAN',plan),('SOURCE',source),('REGISTRY',registry),('REGISTRY_REVIEW',review(registry,source)),
        ('SCENES',scenes),('SCENE_REVIEWS',{x['id']:review(x,source) for x in scenes}),
        ('AUTHORIZATION',{'user_statement':'可以（固定原文事实、验证第1集第7集及新章节）','prior':str(prior),
         'prior_state_sha256':digest(old),'previous_ceiling':previous,'new_ceiling':plan['max_calls'],
         'scope':'3 text expression calls; no free factual rewriting; max6 includes known protocol repairs; no media',
         'holdout_limit':'Chapter55 not used to tune this route; source facts supplied by primary review, not blind model understanding.'})]:freeze(run/(name+'.json'),value)
    for n in (1,7):
        draft=read(prior/f'ADOPTED_EPISODE_{n:02}.json');freeze(run/f'ORIGINAL_EPISODE_{n:02}.json',draft)
    state={**old,'status':'prepared','pending':None,'baseline_calls':old['calls_started'],
           'baseline_tokens':old['reported_tokens'],'scene_candidates':0}
    DirectLedger(run,plan,state,None).save()

def execute(run):
    with run_lock(run):
        import hashlib
        state=read(run/'STATE.json');plan=read(run/'PLAN.json')
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('not_fresh')
        for path,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('implementation_changed')
        source=read(run/'SOURCE.json');registry=read(run/'REGISTRY.json');rr=read(run/'REGISTRY_REVIEW.json')
        scenes=read(run/'SCENES.json');reviews=read(run/'SCENE_REVIEWS.json');ledger=DirectLedger(run,plan,state,NativeClient(run,plan))
        try:
            locked.validate_registry(registry,source,rr)
            candidates={}
            for scene in scenes:
                locked.validate_contract(scene,registry,source,reviews[scene['id']])
                chapters={int(x['evidence']['source_id'].split('-')[0][2:]) for x in scene['lines']}
                expression=ledger.call('PERFORMANCE_'+scene['id'],'writer',
                    '事实、人物、对白说话人、原句与在场位置已核对并锁定。只为每个指定行ID选择schema提供的表演方式。'
                    '结合完整原文选合适语气；不输出或修改姓名、年龄、台词、事件、知情状态。旁白由程序使用原文，不需要添加。',
                    {'scene':scene,'registry':registry,'complete_target_chapters':[x for x in c.indexed_chapters(source) if x['index'] in chapters]},
                    locked.expression_schema(scene))
                candidate=locked.render(scene,registry,source,rr,reviews[scene['id']],expression)
                candidates[scene['id']]=candidate;freeze(run/(scene['id']+'_CANDIDATE.json'),candidate)
                (run/(scene['id']+'.md')).write_text(candidate['screenplay'],encoding='utf-8')
                state['scene_candidates']+=1;ledger.save()
            original=read(run/'ORIGINAL_EPISODE_01.json')
            changes=[{'before':a,'after':b,'reason':'删除无据年龄，保留其他字段待审'} for a,b in [
                ('叶南（少年，约十三四岁）','叶南（少年）'),
                ('叶嫣儿（六岁半，漂亮得像洋娃娃）','叶嫣儿（漂亮得像洋娃娃）'),
                ('叶东（十一岁，瘦高）','叶东（瘦高）')]]
            revised,patch=locked.repair_literal_fields(original,changes)
            freeze(run/'EPISODE_01_PATCH.json',{**patch,'origin':'program_compiled_reviewed_identity_not_model_prose'})
            freeze(run/'EPISODE_01_REPAIRED.json',revised)
            (run/'第1集_年龄字段修正版_其他内容待审.md').write_text(revised['screenplay'],encoding='utf-8')
            original7=read(run/'ORIGINAL_EPISODE_07.json')
            lines=original7['screenplay'].splitlines();bad=[x for x in lines if '妈，你记得吗' in x]
            if len(bad)!=1:raise ValueError('bad_address_span_not_unique')
            spans7=prose_patch.prepare(original7['screenplay'],[{'quote':bad[0],'reason':'称谓/楼下/楼道无据；用已核原文叙述和受限表演表达。'}])
            replacement={'edit_0':candidates['episode7_report']['lines'][0]['text']}
            revised7=locked.repair_spans(original7,spans7,replacement)
            freeze(run/'EPISODE_07_PATCH.json',{'plan':spans7,'replacements':replacement,'origin':'source_fact_plus_native_performance'})
            freeze(run/'EPISODE_07_REPAIRED.json',revised7)
            (run/'第7集_已确认称谓段修正版_其他内容待审.md').write_text(revised7['screenplay'],encoding='utf-8')
            freeze(run/'RESULT.json',{'status':'awaiting_primary_scene_review','unreviewed_handoff_emitted':False,
                 'model_generates':'bounded performance only','registry_origin':'primary_reviewed_source_subset',
                 'full_episode_acceptance':False,'full69_migration':False,'media_ready':False})
            state['status']='awaiting_primary_scene_review'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:3000]})
        finally:ledger.save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute']);p.add_argument('--run',type=Path,required=True);p.add_argument('--prior',type=Path);a=p.parse_args()
    if a.command=='prepare':prepare(a.run,a.prior)
    else:execute(a.run)
