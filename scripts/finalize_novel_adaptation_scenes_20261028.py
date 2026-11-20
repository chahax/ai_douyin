"""Continue the same eight-call scene milestone, using its last two calls."""
import sys
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation import contracts as c,scenes as sc
from src.content_factory.novel_adaptation.patching import bind_patches,retime_beats
from src.content_factory.novel_adaptation.render import episode_markdown

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'data/corpus_production_trials/20261028_adaptation_scenes_scoped_repair'
RUN=ROOT/'data/corpus_production_trials/20261028_adaptation_scenes_final_checks'

def main():
    state0=read(OLD/'STATE.json')
    if state0['pending'] is not None or state0['calls_started']!=1:raise ValueError('known_prefix_required')
    RUN.mkdir(exist_ok=False)
    plan=read(OLD/'PLAN.json');plan.update(max_calls=2,version='novel_adaptation/scenes-empty-transition-defaults')
    source=read(OLD/'SOURCE.json');base=read(OLD/'BEFORE.json');patch=read(OLD/'TARGETED_PATCH.json')
    packet=read(OLD.parent/'20261028_adaptation_scenes_design_repair/PACKET.json')
    entities={'entities':packet['entities']};facts=[f['id'] for f in packet['facts']]
    recovered=deepcopy(base);recovered['design']['world_framework']=patch['world_framework'];recovered['design']['visual_design']=patch['visual_design']
    for p in recovered['design']['props']:
        if p['id']=='iodine-bottle':p['description']=patch['iodine_description']
    for i,k in enumerate(['scene1_patches','scene2_patches']):
        proposals=deepcopy(patch[k])
        for proposal in proposals:
            proposal['replacement']=sc.normalize_scene({'beats':[proposal['replacement']]})['beats'][0]
        old=base['scenes'][i];allowed={x['id'] for x in proposals}
        raw=c.apply_record_patches(old,bind_patches(old,proposals,allowed,digest(old)),allowed,digest(old),lambda _:None)
        recovered['scenes'][i],duration=retime_beats(raw);recovered['design']['scenes'][i]['duration_seconds']=duration
    freeze(RUN/'RECOVERED_UNACCEPTED.json',recovered)
    freeze(RUN/'RECOVERY.json',{'native_patch_sha256':digest(patch),'defaults':['missing moves=[]','missing transfers=[]'],
        'meaning':'new explicit empty-transition contract; no text changes, original failure retained','semantic_acceptance':False})
    freeze(RUN/'PLAN.json',plan);freeze(RUN/'SOURCE.json',source)
    freeze(RUN/'AUTHORIZATION.json',{'original_scene_bound':8,'prior_used':6,'remaining':2,'book_prior_starts':173,'scope':'same authorized novel text only'})
    freeze(OLD/'BUDGET_TRANSFER.json',{'child':str(RUN),'original_scene_bound':8,'prior_used':6,'remaining':2})
    snapshot=RUN/'implementation';snapshot.mkdir()
    for file in [Path(__file__),Path(c.__file__),Path(sc.__file__),ROOT/'src/content_factory/novel_adaptation/patching.py']:
        (snapshot/file.name).write_bytes(file.read_bytes())
    state={'status':'prepared','calls_started':0,'reported_tokens':0,'pending':None};ledger=Ledger(RUN,plan,state,NativeClient(RUN,plan));ledger.save()
    try:
        item=sc.scene_schema(recovered['design'],entities,facts,source)['properties']['beats']['items']
        schema=c.obj(first_scene=c.array(c.obj(id=c.choices(['b01','b09']),replacement=item),2),
            second_scene=c.array(c.obj(id=c.choices(['b09']),replacement=item),1),
            visual=c.array(c.obj(index={'type':'integer','enum':[3,8]},description=c.TEXT,basis=c.choices(['source_constraint','adaptation_design'])),2))
        response=ledger.call('FINAL_TARGETED_PATCH','writer','''只修指定字段，其他稿件已固定。
第一场b01内心台词在原2.4秒里过长，缩短文字，不改beat与audio时间。
第一场b09的present定义是move完成后房间内的人（不是整段曾入镜人员）：孩子已跑出去，仅苏墨留下。改present并改adaptation_detail相应说明，其他动作台词时间均保持。
第二场b09不要把很多土豆改成满满一袋，原文第2章是大半袋，当前第一章只需很多，其他时间和动作保持。所有时间用提供的当前场次绝对秒，不改起止秒。
视觉条目index3和8混合原文与设计（枕头塌陷、叶东稍壮实等未明示），把描述限定为原文明示事实，或者明确basis=adaptation_design，不冒称额外细节是原文。
只返回这两条视觉条目和三条beat，保持id。moves/transfers没有变化时可以空数组，省略也定义为空；有变化须明确列出。''',
            {'candidate':recovered,'complete_chapters':c.indexed_chapters(source)},schema)
        errors=c.schema_issues(response,schema,'patch')
        if errors:raise c.ContractError(errors)
        after=deepcopy(recovered)
        for i,key,allowed in [(0,'first_scene',{'b01','b09'}),(1,'second_scene',{'b09'})]:
            proposals=response[key]
            if {p['id'] for p in proposals}!=allowed:raise ValueError('patch_coverage')
            for p in proposals:
                p['replacement']=sc.normalize_scene({'beats':[p['replacement']]})['beats'][0]
                old=next(b for b in after['scenes'][i]['beats'] if b['id']==p['id'])
                if old['start']!=p['replacement']['start'] or old['end']!=p['replacement']['end']:raise ValueError('unauthorized_retime')
            old=after['scenes'][i]
            after['scenes'][i]=c.apply_record_patches(old,bind_patches(old,proposals,allowed,digest(old)),allowed,digest(old),lambda _:None)
        if {r['index'] for r in response['visual']}!={3,8} or len(response['visual'])!=2:raise ValueError('visual_scope')
        for r in response['visual']:
            after['design']['visual_design'][r['index']].update(description=r['description'],basis=r['basis'])
        previous=sc.initial_state(after['design'],entities)
        for scene,spec in zip(after['scenes'],after['design']['scenes']):
            previous=sc.advance(scene,spec,after['design'],entities,facts,source,previous)
        after['end_state']=previous;freeze(RUN/'EPISODE.json',after)
        (RUN/'EPISODE_UNACCEPTED.md').write_text(episode_markdown(after,entities),encoding='utf-8')
        schema=c.obj(verdict=c.choices(['pass','revise','uncertain']),issues=c.array(c.obj(path=c.TEXT,problem=c.TEXT,source_ids=c.refs(c.catalog(source)),severity=c.choices(['must_fix','suggestion','uncertain']))))
        review=ledger.call('FINAL_REVIEW','writer','''独立审核完整第一章改编候选：原文事实、世界框架、人物关系、进出场、道具、说话/内心/叙述、时间与信息节奏。可进行标明的影视动作补足，不能无据新增重大因果。逐条判断当前稿，不引用旧审核。必须明确原文依据，不把建议当硬伤。''',
            {'complete_chapters':c.indexed_chapters(source),'candidate':after,'candidate_sha256':digest(after)},schema)
        errs=c.schema_issues(review,schema,'review')
        if errs:raise c.ContractError(errs)
        state['status']='episode_awaiting_primary_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(RUN/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:5000]})
    finally:ledger.save()

if __name__=='__main__':main()
