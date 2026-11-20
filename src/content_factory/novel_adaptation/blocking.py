"""Single-source typed blocking compiled into prose and state transitions.

Opt-in experimental contract. Unsupported actions require a vocabulary extension;
this is not a semantic proof of dialogue or source selection.
"""
from copy import deepcopy
from . import contracts as c,scenes as sc
from .presentation import display_names

GESTURES={"look_at":"看向","smile_at":"朝着对方微笑","nod_to":"向对方点头",
 "pat_head":"轻轻摸了摸对方的头","open_bag":"展开袋口","show":"展示",
 "clench_fists":"攥紧拳头","step_toward":"向对方靠近","embrace":"轻轻抱住","stand":"站起身","kneel":"跪下",
 "cut":"切开","trim":"修整坏处","peel":"削去芽眼与坏处","stir":"搅拌","eat":"进食","point_at":"指向","close_door":"关上门",
 "pull_hem":"拉住对方衣角","push_out":"将对方推向门外","light_stove":"点燃炉火"}
FRAMING={"wide":"全景","medium":"中景","close":"近景","detail":"特写"}
MOTION={"static":"固定机位","slow_pan":"平稳横移","slow_push":"缓慢推进","follow":"平稳跟随"}
ANGLE={"eye":"平视","low":"低机位","high":"俯视"}
SELF_GESTURES={'clench_fists','stand','kneel'}


def action_contract_prompt(plan):
    if plan.get('action_contract_version') != 2:return ''
    return '''\n动作合同v2：gesture.target是受动作影响的对象，instrument是本人已拿在手里的工具，两者必须不同。cut/trim/peel/stir必须填写instrument；先拿工具再使用，容器内的工具先unpack。
recipe.input_containers明确指定加工容器时，对应原料须先pack进该容器，再transform；此字段未指定的原料须先取出容器。完成后已消耗原料不再保留在锅内，不把成品和原料重复展示。
recipe.output_containers指定成品所在容器时，transform自动登记成品在该容器内并与容器同属；容器须本地可用，不能靠台词假设容器关系。
入场move可显式carry_from_origin：从出发房间取来列出的道具并随本人进入当前场，出发房间必须与人物前态位置一致，道具须属于该房间且不在其他容器内。完整容器中的内容随行。已经本人持有的物品自动随本人移动，不重复列入。当前场不是中间走廊时，入场move直接写真实出发房间到当前场，不在单场里演出多房路线。
transform只表示已审核recipe的完成状态转换。completion_action只写此刻完成制作的具体可见动作，不复述recipe.action全过程；此前必要制作动作仍须按顺序用blocking演出。内心说准备做某事、look_at或point_at不等于已经执行该事。'''


def blocking_schema(plan,entities,fact_ids,source,previous,evidence_ids,*,allow_silent_omission=False):
    schema=sc.model_scene_schema(plan,entities,fact_ids,source,previous,evidence_ids)
    beat=schema["properties"]["beats"]["items"];props=beat["properties"]
    if allow_silent_omission:beat['required'].remove('audio')
    props['audio']['default']=[]
    props['audio']['description']='Explicit actual audio. Use [] only for intentional silence. Speech described elsewhere does not create audio.'
    people=[e["id"] for e in entities["entities"] if e["kind"]=="character"]
    objects=[p["id"] for p in plan["props"]];places=[p["id"] for p in plan["places"]]
    variants=[]
    for kind,field in (("move","moves"),("transfer","transfers")):
        item=deepcopy(props[field]["items"]);item["properties"].pop("action");item["required"].remove("action")
        if kind=='transfer' and not plan.get('container_actions'):
            item['properties']['prop']=c.choices([p for p in objects if p not in (previous or {}).get('containers',{})])
        item["properties"]["kind"]=c.choices([kind]);item["required"].append("kind");variants.append(item)
    for kind,field in [('unpack','unpacks'),('pack','packs'),('transform','transforms')]:
        if props[field].get('items') is False:continue
        item=deepcopy(props[field]['items']);item['properties']['kind']=c.choices([kind]);item['required'].append('kind');variants.append(item)
        if kind=='transform' and plan.get('action_contract_version')==2:item['required'].append('completion_action')
    gesture=c.obj(kind=c.choices(["gesture"]),actor=c.choices(people),verb=c.choices(GESTURES),
                  target=c.choices(people+objects+places))
    gesture['properties']['instrument']=c.choices(objects)
    gesture['properties']['instrument']['description']='Tool held by actor, distinct from target (the affected object).'
    timing=props["moves"]["items"]
    for field in ("phase","after_audio_index"):gesture["properties"][field]=deepcopy(timing["properties"][field])
    gesture['required'].remove('target')
    gesture["allOf"]=deepcopy(timing["allOf"])+[{'if':{'properties':{'verb':{'enum':sorted(SELF_GESTURES)}},'required':['verb']},'then':{},'else':{'required':['target']}}];variants.append(gesture)
    if plan.get('action_contract_version') == 2:
        gesture['allOf'].append({'if':{'properties':{'verb':{'enum':['cut','trim','peel','stir']}},'required':['verb']},'then':{'required':['instrument']}})
    for field in ("action","camera","moves","transfers","prop_uses","gestures","shot_subjects","action_order","unpacks","packs","transforms"):
        props.pop(field);beat["required"]=[x for x in beat["required"] if x!=field]
    props["blocking"]=c.array({"oneOf":variants},1);beat["required"].append("blocking")
    props["shot"]=c.obj(framing=c.choices(FRAMING),motion=c.choices(MOTION),angle=c.choices(ANGLE),
        subjects=c.refs(people+objects+places))
    beat["required"].append("shot")
    return schema


def compile_blocking(raw,plan,entities,source_schema):
    errors=c.schema_issues(raw,source_schema,"blocking")
    if errors:raise c.ContractError(errors)
    names=display_names(plan,entities)
    result=deepcopy(raw)
    for beat in result["beats"]:
        beat.setdefault('audio',[])
        text=[];beat["moves"]=[];beat["transfers"]=[];beat["prop_uses"]=[];beat["gestures"]=[]
        for field in ('unpacks','packs','transforms'):beat[field]=[]
        beat['action_order']=[]
        def append(field,row):
            beat['action_order'].append({'field':field,'index':len(beat[field])})
            beat[field].append(row)
        # Phases establish time; list order establishes order within each phase.
        events=beat.pop('blocking')
        def moment_key(e):
            phase=e.get('phase','start')
            return -1 if phase=='start' else len(beat['audio']) if phase=='end' else e['after_audio_index']
        for event in sorted(events,key=moment_key):
            phase=event.get("phase","start")
            moment=("本段开始时" if phase=="start" else "本段对白结束后" if phase=="end"
                    else "第"+str(event["after_audio_index"]+1)+"句音轨结束后")
            if event["kind"]=="transfer":
                sentence=names[event["origin"]]+"将"+names[event["prop"]]+"移交至"+names[event["destination"]]
                append("transfers",{k:v for k,v in event.items() if k!="kind"}|{"action":sentence})
            elif event["kind"]=="move":
                sentence=names[event["person"]]+"从"+names[event["origin"]]+"来到"+names[event["destination"]]
                if event.get('carry_from_origin'):
                    sentence=names[event['person']]+'从'+names[event['origin']]+'取来'+ '、'.join(names[p] for p in event['carry_from_origin'])+'，携物来到'+names[event['destination']]
                append("moves",{k:v for k,v in event.items() if k!="kind"}|{"action":sentence})
            elif event['kind'] in ('unpack','pack','transform'):
                kind=event['kind'];field={'unpack':'unpacks','pack':'packs','transform':'transforms'}[kind]
                append(field,{k:v for k,v in event.items() if k!='kind'})
                if kind=='unpack':sentence=names[event['actor']]+'从'+names[event['container']]+'取出'+names[event['prop']]+'，交由'+names[event['destination']]+'承接'
                elif kind=='pack':sentence=names[event['actor']]+'把'+names[event['prop']]+'装入'+names[event['container']]
                else:
                    recipe=next(r for r in plan['recipes'] if r['id']==event['recipe'])
                    performance=event['completion_action'] if plan.get('action_contract_version') == 2 else recipe['action']
                    sentence=names[event['actor']]+'：'+performance+'；成品由'+names[event['destination']]+'承接'
            else:
                if event['verb'] in SELF_GESTURES and 'target' not in event:event['target']=event['actor']
                append("gestures",{k:v for k,v in event.items() if k!="kind"})
                sentence=names[event["actor"]]+"："+GESTURES[event["verb"]]+"（"+names[event["target"]]+"）"
                if event.get('instrument'):
                    sentence=names[event['actor']]+'：用'+names[event['instrument']]+GESTURES[event['verb']]+'（'+names[event['target']]+'）'
                if event["verb"] == "show":
                    timing={k:event[k] for k in ("phase","after_audio_index") if k in event}
                    append("prop_uses",{"prop":event["target"],"holder":event["actor"],**timing})
            text.append(moment+"，"+sentence+"。")
        shot=beat.pop("shot");beat["shot_subjects"]=shot["subjects"]
        beat["camera"]=ANGLE[shot["angle"]]+"，"+FRAMING[shot["framing"]]+"，"+MOTION[shot["motion"]]+"；画面主体："+ "、".join(names[x] for x in shot["subjects"])+"。"
        beat["action"]="".join(text)
    return result
