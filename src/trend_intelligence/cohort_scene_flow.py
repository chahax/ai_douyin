"""Executable story events and bounded scene writing; never media approval.

The planner chooses events. Python derives state/financial results from operations,
not from an author-written end_state or ending paragraph.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re

SCHEMA='cohort_event_contract/v2'

class FlowError(ValueError):
    def __init__(self,code,message,stage='contract',beat_id=None):
        super().__init__(message);self.code=code;self.stage=stage;self.beat_id=beat_id
    def report(self):return {'code':self.code,'message':str(self),'repair_stage':self.stage,'beat_id':self.beat_id}

def fail(code,message,stage='contract',beat=None):raise FlowError(code,message,stage,beat)

def strict_json(raw):
    def unique(items):
        result={}
        for k,v in items:
            if k in result:fail('duplicate_key',f'Duplicate key: {k}','format')
            result[k]=v
        return result
    try:return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda x:fail('nonfinite',x,'format'))
    except json.JSONDecodeError as e:fail('invalid_json',str(e),'format')

def signature(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def nonempty(value,label):
    if not isinstance(value,str) or not value.strip():fail('missing_text',label)

def number(value,label,minimum,maximum):
    if type(value) not in (int,float) or not math.isfinite(value) or not minimum<=value<=maximum:
        fail('invalid_number',label)

def require_keys(value,keys,label):
    if not isinstance(value,dict) or set(value)!=set(keys):fail('shape',label+': '+','.join(keys),'format')

def is_hand(location,actor=None):
    if actor:return location in (f'{actor}:left',f'{actor}:right')
    return bool(re.fullmatch(r'[^:]+:(left|right)',location))

def allocate(beats,kind):
    total={'short':45.,'long':180.}.get(kind)
    if total is None:fail('kind','Unknown version')
    groups={'setup':[],'pressure':[],'ending':[]}
    for b in beats:
        role=b['role']
        group='setup' if role=='setup' else 'ending' if role in ('resolution','closure') else 'pressure'
        if role not in ('setup','conflict','escalation','turn','resolution','closure'):fail('beat_role',role)
        number(b['weight'],'beat weight',.25,4)
        groups[group].append(b)
    if not groups['pressure'] or not groups['ending'] or not any(b['role']=='turn' for b in beats):
        fail('missing_arc','Conflict, turn and visible resolution required')
    setup=total*.04 if groups['setup'] else 0
    budgets={'setup':setup,'pressure':total*.8-setup,'ending':total*.2}
    seconds={}
    for group,members in groups.items():
        minima={b['id']:sum({'move':.5,'show':2,'ack':.2,'agree':.2,'submit':3,'receive':1.2}.get(op[0],0) for op in b['ops'])
            +b['pause']+(.6 if b['speakers'] else 0) for b in members}
        leftover=budgets[group]-sum(minima.values())
        if leftover<-.00001:fail('action_budget',f'{group} needs {sum(minima.values()):.2f}s, budget is {budgets[group]:.2f}s')
        voiced=[b for b in members if b['speakers']]
        weight=sum(b['weight'] for b in voiced)
        if members and not voiced and leftover>.05:fail('empty_padding',f'{group}: {leftover:.2f}s has no authored action or dialogue')
        for b in members:seconds[b['id']]=minima[b['id']]+(leftover*b['weight']/weight if b['speakers'] else 0)
    return seconds

def replay(contract,allowed_sources=None):
    require_keys(contract,('schema','kind','title','goal','space','characters','locations','props','facts','transactions','terminal','references','beats'),'contract')
    if contract['schema']!=SCHEMA:fail('schema','Wrong contract schema')
    for key in ('title','goal','space'):nonempty(contract[key],key)
    actors=contract['characters'];props=contract['props'];facts=contract['facts'];transactions=contract['transactions']
    if not isinstance(actors,dict) or len(actors)<2:fail('actors','At least two on-screen actors required')
    for aid,a in actors.items():
        require_keys(a,('name','position'),'actor');nonempty(a['name'],'actor name');nonempty(a['position'],'actor position')
    if len({a['name'] for a in actors.values()})!=len(actors):fail('actors','Duplicate actor name')
    locations=contract['locations']
    if not isinstance(locations,list) or len(locations)!=len(set(locations)):fail('locations','Unique locations required')
    for loc in locations:
        nonempty(loc,'location')
        if ':' in loc and loc.split(':')[0] not in actors:fail('locations','Unknown location actor')
    state={'props':{},'seen':{},'shown_in_scene':{},'confirmed':{},'transactions':{}}
    for pid,p in props.items():
        require_keys(p,('name','owner','location'),'prop')
        nonempty(p['name'],'prop name')
        if p['owner'] not in actors or p['location'] not in locations:fail('prop_identity',pid)
        state['props'][pid]=p['location']
    def hands(beat=None):
        held=[v for v in state['props'].values() if is_hand(v)]
        if len(set(held))!=len(held):
            occupied={loc:[p for p,v in state['props'].items() if v==loc] for loc in held if held.count(loc)>1}
            fail('occupied_hand',f'{beat or "initial"}: occupied hand {occupied}; move existing prop first or choose a free hand',beat=beat)
    hands()
    for fid,f in facts.items():
        require_keys(f,('text','kind','prop','initial_knowers'),'fact')
        nonempty(f['text'],'fact text')
        if f['kind'] not in ('evidence','agreement'):fail('fact_kind',fid)
        if f['kind']=='evidence' and f['prop'] not in props:fail('evidence_prop',fid)
        if f['kind']=='agreement' and f['prop'] is not None:fail('agreement_prop',fid)
        if not isinstance(f['initial_knowers'],list) or not set(f['initial_knowers'])<=set(actors):fail('fact_knowers',fid)
        state['seen'][fid]=list(f['initial_knowers']);state['confirmed'][fid]=list(f['initial_knowers'])
        state['shown_in_scene'][fid]=[]
    for tid,t in transactions.items():
        require_keys(t,('payer','payee','amount','payer_prop','payee_prop','agreement','requires'),'transaction')
        if t['payer'] not in actors or t['payee'] not in actors or t['payer']==t['payee']:fail('payment_identity',tid)
        nonempty(t['amount'],'spoken amount')
        for role in ('payer','payee'):
            prop=t[role+'_prop']
            if prop not in props or props[prop]['owner']!=t[role]:fail('payment_device_owner',tid)
        if t['agreement'] not in facts or facts[t['agreement']]['kind']!='agreement':fail('payment_agreement',tid)
        if not isinstance(t['requires'],list) or not set(t['requires'])<=set(facts):fail('payment_prerequisites',tid)
        state['transactions'][tid]='unsubmitted'
    refs=contract['references']
    if not isinstance(refs,list) or not refs:fail('references','Source expression transfer required')
    for ref in refs:
        require_keys(ref,('source_id','evidence_ids','use'),'reference')
        nonempty(ref['use'],'reference use')
        if not ref['evidence_ids']:fail('reference_evidence','Empty evidence')
        if allowed_sources is not None and (ref['source_id'] not in allowed_sources or not set(ref['evidence_ids'])<=set(allowed_sources[ref['source_id']])):
            fail('reference_identity','Source ID/evidence mismatch','research')
    beats=contract['beats']
    if not isinstance(beats,list) or not 3<=len(beats)<=30:fail('beats','Invalid beat count')
    ids=[b.get('id') for b in beats]
    if len(set(ids))!=len(ids):fail('beat_identity','Duplicate beat')
    durations=allocate(beats,contract['kind']);trace=[];cursor=0
    for b in beats:
        require_keys(b,('id','role','weight','intent','trigger','emotion','cps','pause','speakers','framing','ops'),'beat')
        for key in ('id','intent','trigger','emotion','framing'):nonempty(b[key],key)
        number(b['cps'],'delivery cps',4.3,5.7);number(b['pause'],'pause',0,1.2)
        if not isinstance(b['speakers'],list) or not set(b['speakers'])<=set(actors):fail('speaker','Unknown on-screen speaker')
        before=copy.deepcopy(state);actions=[];operation_seconds=0
        def name(a):return actors[a]['name']
        for op in b['ops']:
            if not isinstance(op,list) or not op:fail('operation','Invalid operation',beat=b['id'])
            code=op[0]
            if code=='move' and len(op)==4:
                _,pid,src,dst=op
                if pid not in props or state['props'][pid]!=src or dst not in locations or src==dst:
                    fail('prop_transition',f'{b["id"]}: {op}; actual={state["props"].get(pid)}',beat=b['id'])
                state['props'][pid]=dst;hands(b['id']);operation_seconds+=.5
                actions.append(f'{props[pid]["name"]}：{src} → {dst}（实际取出/放下/转交）。')
            elif code=='show' and len(op)==4:
                _,fid,actor,viewer=op
                if fid not in facts or facts[fid]['kind']!='evidence' or actor not in actors or viewer not in actors or actor==viewer:
                    fail('reveal_identity',str(op),beat=b['id'])
                if actor not in state['seen'][fid] or not is_hand(state['props'][facts[fid]['prop']],actor):
                    fail('unavailable_evidence',str(op),beat=b['id'])
                if viewer not in state['seen'][fid]:state['seen'][fid].append(viewer)
                if viewer not in state['shown_in_scene'][fid]:state['shown_in_scene'][fid].append(viewer)
                actions.append(f'{name(actor)}展示{props[facts[fid]["prop"]]["name"]}中的记录，让{name(viewer)}和镜头实际看到：{facts[fid]["text"]}。')
                operation_seconds+=2
            elif code=='ack' and len(op)==3:
                _,fid,actor=op
                if fid not in facts or facts[fid]['kind']!='evidence' or actor not in state['shown_in_scene'][fid]:
                    fail('ack_without_evidence',str(op),beat=b['id'])
                if actor not in state['confirmed'][fid]:state['confirmed'][fid].append(actor)
                actions.append(f'{name(actor)}核对后明确确认：{facts[fid]["text"]}。');operation_seconds+=.2
            elif code=='agree' and len(op)==3:
                _,fid,actor=op
                if fid not in facts or facts[fid]['kind']!='agreement' or actor not in actors:fail('agreement',str(op),beat=b['id'])
                if actor not in state['confirmed'][fid]:state['confirmed'][fid].append(actor)
                actions.append(f'{name(actor)}现场明确同意：{facts[fid]["text"]}。');operation_seconds+=.2
            elif code in ('submit','receive') and len(op)==3:
                _,tid,actor=op
                if tid not in transactions:fail('payment_identity',str(op),beat=b['id'])
                t=transactions[tid];role='payer' if code=='submit' else 'payee'
                if actor!=t[role]:fail('reversed_payment',f'{code} must be performed by {t[role]}',beat=b['id'])
                if not is_hand(state['props'][t[role+'_prop']],actor):fail('payment_device_unavailable',str(op),beat=b['id'])
                if code=='submit':
                    if state['transactions'][tid]!='unsubmitted':fail('duplicate_payment',tid,beat=b['id'])
                    if t['payer'] not in state['confirmed'][t['agreement']] or any(not {t['payer'],t['payee']}<=set(state['confirmed'][f]) for f in t['requires']):
                        fail('payment_before_agreement','Payment requires confirmed evidence and payer agreement',beat=b['id'])
                    if any(not state['shown_in_scene'][f] for f in t['requires']):fail('unshown_evidence','Required evidence never shown on screen',beat=b['id'])
                    state['transactions'][tid]='submitted';operation_seconds+=3
                    actions.append(f'{name(actor)}在自己的{props[t["payer_prop"]]["name"]}上选择{name(t["payee"])}为收款人，核对金额{t["amount"]}后提交付款。')
                else:
                    if state['transactions'][tid]!='submitted':fail('receipt_without_payment',tid,beat=b['id'])
                    state['transactions'][tid]='received';operation_seconds+=1.2
                    actions.append(f'{name(actor)}打开自己的{props[t["payee_prop"]]["name"]}收款记录；镜头看到来自{name(t["payer"])}的{t["amount"]}入账，由{name(actor)}确认。')
            else:fail('unknown_operation',str(op),beat=b['id'])
        duration=durations[b['id']]
        if operation_seconds>duration:fail('action_overflow',f'{b["id"]} needs at least {operation_seconds}s, has {duration:.2f}s',beat=b['id'])
        if b['speakers'] and duration-operation_seconds-b['pause']<.5999:fail('no_speech_time',b['id'],beat=b['id'])
        if not b['speakers'] and (not b['ops'] or duration-operation_seconds-b['pause']>.05):fail('empty_padding','Silent beat needs concrete operations only',beat=b['id'])
        trace.append({'beat':copy.deepcopy(b),'start':cursor,'end':cursor+duration,'duration':duration,
            'before':before,'after':copy.deepcopy(state),'actions':actions,'minimum_action_seconds':operation_seconds})
        cursor+=duration
    terminal=contract['terminal'];require_keys(terminal,('props','transactions','confirmed'),'terminal')
    for key,val in terminal['props'].items():
        if key not in props or state['props'][key]!=val:fail('terminal_prop',f'{key}: expected {val}, actual {state["props"].get(key)}')
    for key,val in terminal['transactions'].items():
        if key not in transactions or val!='received' or state['transactions'][key]!=val:fail('unrealized_result','Receipt not actually reached: '+key)
    if set(terminal['transactions'])!=set(transactions):fail('unrealized_result','Every planned transfer needs receiver confirmation')
    for fid,who in terminal['confirmed'].items():
        if fid not in facts or not set(who)<=set(state['confirmed'][fid]):fail('terminal_fact',fid)
    if not terminal['props'] and not terminal['transactions'] and not terminal['confirmed']:fail('empty_goal','Observable terminal goal required')
    return {'schema':'cohort_event_trace/v2','contract_sha256':signature(contract),'duration':cursor,'beats':trace,'terminal':state,
        'status':'structurally_valid_pending_actual_review','semantic_review_required':True}

def scene_request(contract,trace_row):
    return {'schema':'cohort_scene_request/v3','pacing_metric':'spoken_characters_excluding_punctuation','cast':contract['characters'],'props':contract['props'],
        'space':contract['space'],'goal':contract['goal'],'facts':contract['facts'],'transactions':contract['transactions'],
        'beat':trace_row,'notice':'只写本段现场对白。动作与状态已经冻结，不能改剧情、付款方向、金额或道具；不复制其他段。'}

def spoken_characters(text):
    """Declared Chinese speech budget excludes punctuation and whitespace."""
    return sum(c.isalnum() for c in text)


def monetary_mentions(text):
    mentions=[]
    for m in re.finditer(r'([零〇一二两三四五六七八九十百千万亿]+)(元|块钱|块)?',text):
        if not m.group(2) and (not any(x in m.group(1) for x in '零〇一二两三四五六七八九十') or re.match(r'(次|遍|天|年|分钟|个人|个人|个|别)',text[m.end():])):continue
        if m.group(2) or any(x in m.group(1) for x in '百千万亿'):mentions.append(m.group(1))
    return mentions


def validate_lines(value,contract,row,strict_timing=True):
    require_keys(value,('lines',),'scene dialogue')
    lines=value['lines']
    if not row['beat']['speakers']:
        if lines!=[]:fail('unexpected_speech','No speech in frozen action-only beat','dialogue',row['beat']['id'])
        return {'lines':[],'rate':None,'characters':0,'spoken_seconds':0,'pause':row['beat']['pause']}
    if not isinstance(lines,list) or not 1<=len(lines)<=3:fail('line_count','One to three utterances per beat','dialogue',row['beat']['id'])
    seconds=row['duration']-row['minimum_action_seconds']-row['beat']['pause'];count=0
    for d in lines:
        require_keys(d,('speaker','text'),'line')
        if d['speaker'] not in row['beat']['speakers']:fail('offscreen_speaker','Speaker differs from frozen beat','dialogue',row['beat']['id'])
        nonempty(d['text'],'spoken dialogue')
        if re.search(r'\d|[\r\n]|[（(]|旁白|后台改不了|日期改不了',d['text']):
            fail('invalid_spoken_content','Only actual on-screen speech with spoken numbers; no known false date guarantee','dialogue',row['beat']['id'])
        amounts={x for t in contract['transactions'].values() for x in monetary_mentions(t['amount'])}
        if any(x not in amounts for x in monetary_mentions(d['text'])):
            fail('invented_amount','Dialogue introduces an amount absent from frozen transactions','dialogue',row['beat']['id'])
        count+=spoken_characters(d['text'])
    rate=count/seconds
    if strict_timing and (not 4.3-1e-8<=rate<=5.7+1e-8 or abs(rate-row['beat']['cps'])>.8+1e-8):
        fail('scene_pacing',f'{row["beat"]["id"]}: {count} chars in {seconds:.2f}s gives {rate:.2f}; need {math.ceil(4.3*seconds)}—{math.floor(5.7*seconds)} chars','dialogue',row['beat']['id'])
    return {'lines':copy.deepcopy(lines),'rate':rate,'characters':count,'spoken_seconds':seconds,'pause':row['beat']['pause']}


def fit_dialogue_timing(contract,trace,scenes):
    """Fit authored speech within local delivery bounds; never shorten operations."""
    result=copy.deepcopy(trace);items=[]
    for row,scene in zip(result['beats'],scenes,strict=True):
        checked=validate_lines(scene,contract,row,strict_timing=False)
        count=checked['characters'];b=row['beat'];fixed=row['minimum_action_seconds']+b['pause']
        if count:
            low=count/min(5.7,b['cps']+.8);high=count/max(4.3,b['cps']-.8)
            preferred=count/b['cps']
        else:low=high=preferred=0
        items.append({'fixed':fixed,'low':low,'high':high,'speech':preferred})
    available=trace['duration']-sum(x['fixed'] for x in items)
    low=sum(x['low'] for x in items);high=sum(x['high'] for x in items)
    if not low-1e-8<=available<=high+1e-8:
        fail('whole_dialogue_budget',f'Speech needs {low:.2f}—{high:.2f}s; available {available:.2f}s. Revise redundant or insufficient content; do not pad silence or speed up actions.','dialogue')
    delta=available-sum(x['speech'] for x in items)
    room=[(x['high']-x['speech']) if delta>=0 else (x['speech']-x['low']) for x in items]
    total=sum(room)
    for x,r in zip(items,room,strict=True):x['speech']+=delta*r/total if total else 0
    cursor=0
    for row,x in zip(result['beats'],items,strict=True):
        row['start']=cursor;row['duration']=x['fixed']+x['speech'];cursor+=row['duration'];row['end']=cursor
    result['timing_method']='authored_speech_with_local_delivery_bounds/v1'
    for row,scene in zip(result['beats'],scenes,strict=True):validate_lines(scene,contract,row)
    return result


def apply_direction_revision(trace,revision,scenes):
    require_keys(revision,('dialogue_sha256','overrides'),'direction revision')
    if revision['dialogue_sha256']!=signature(scenes):fail('stale_direction','Direction revision belongs to different dialogue','direction')
    result=copy.deepcopy(trace);by_id={r['beat']['id']:r for r in result['beats']}
    for bid,fields in revision['overrides'].items():
        if bid not in by_id or not fields or not set(fields)<={'trigger','emotion','framing','intent'}:
            fail('direction_scope','Direction revision cannot change event operations, speaker identity or timing','direction')
        for key,value in fields.items():nonempty(value,key);by_id[bid]['beat'][key]=value
    return result


def check_direction_quotes(trace,scenes):
    spoken=''.join(d['text'] for scene in scenes for d in scene['lines'])
    issues=[]
    for row in trace['beats']:
        for field in ('trigger','emotion'):
            for quote in re.findall(r'「([^」]+)」|“([^”]+)”',row['beat'][field]):
                text=next(x for x in quote if x)
                if text not in spoken:issues.append({'beat_id':row['beat']['id'],'field':field,'quote':text})
    return issues

def render(contract,trace,scenes):
    out=[f'# {contract["title"]} · {trace["duration"]:.0f}秒','', '虚构情节演绎。', '', contract['goal'],'',contract['space'],'']
    out+=['人物初始位置：'+'；'.join(f'{v["name"]}：{v["position"]}' for v in contract['characters'].values()),
          '初始道具：'+'；'.join(f'{v["name"]}={v["location"]}' for v in contract['props'].values()),'']
    for i,(row,scene) in enumerate(zip(trace['beats'],scenes,strict=True)):
        checked=validate_lines(scene,contract,row);b=row['beat'];cursor=row['start']+row['minimum_action_seconds']
        out += [f'## {b["id"]} · {row["start"]:.2f}—{row["end"]:.2f}秒','',b['framing'],
            f'本段推进：{b["intent"]}',f'情绪触发：{b["trigger"]}；表现：{b["emotion"]}；'+(f'声明语速：{checked["rate"]:.2f}字/秒。' if checked['rate'] else '本段以实际动作收束，无对白。'),'',
            f'先完成下列操作（预留至少{row["minimum_action_seconds"]:.2f}秒），再说本段对白；实际执行如需更久，应退回事件排时，不加速掩盖。']
        out += ['- '+a for a in row['actions']]
        out.append('')
        if checked['lines']:
            out.append('对白镜头：回到既定视线轴同侧的人物中近景，以下说话人的嘴部可见；物件特写不承担画外对白。')
        for d in checked['lines']:
            end=cursor+spoken_characters(d['text'])/checked['rate']
            out.append(f'- {contract["characters"][d["speaker"]]["name"]}【{cursor:.3f}-{end:.3f}秒】：{d["text"]}')
            cursor=end
        out += ['',f'段末反应时间：{b["pause"]}秒；反应对应上述情绪触发，不新增动作结果。',
            '道具末态：'+'；'.join(f'{contract["props"][k]["name"]}={v}' for k,v in row['after']['props'].items()),'']
    out+=['## 实际终态','',json.dumps(trace['terminal'],ensure_ascii=False,indent=2),'',
        '## 来源表达借鉴','']+[f'- {r["source_id"]}（{", ".join(r["evidence_ids"])}）：{r["use"]}' for r in contract['references']]
    out+=['','状态和声明排时校验不能证明表演、法律解释或实际声画已经通过。']
    return '\n'.join(out)+'\n'

def apply_plan_replacements(candidate,patch,allowed_paths):
    """Exact pointer replacements; no whole-document regeneration or mutation."""
    require_keys(patch,('replacements',),'plan patch')
    rows=patch['replacements']
    if not isinstance(rows,list) or not rows:fail('empty_patch','No replacements','format')
    paths=[r.get('path') for r in rows]
    if len(paths)!=len(set(paths)) or set(paths)!=set(allowed_paths):
        fail('patch_scope',f'Patch scope mismatch: missing={sorted(set(allowed_paths)-set(paths))}; extra={sorted(set(paths)-set(allowed_paths))}; duplicate_count={len(paths)-len(set(paths))}. Copy exact zero-based pointers from replacement targets.','format')
    if any(a!=b and b.startswith(a+'/') for a in paths for b in paths):fail('patch_overlap','Overlapping replacement fields','format')
    result=copy.deepcopy(candidate)
    for row in rows:
        require_keys(row,('path','value'),'replacement')
        path=row['path']
        if not isinstance(path,str) or not path.startswith('/') or path=='/':fail('patch_pointer','Field pointer required','format')
        parts=path[1:].split('/');target=result
        for part in parts[:-1]:target=target[int(part)] if isinstance(target,list) else target[part]
        key=int(parts[-1]) if isinstance(target,list) else parts[-1]
        if isinstance(target,dict) and key not in target:fail('patch_pointer','Cannot invent a replacement target','format')
        target[key]=copy.deepcopy(row['value'])
    return result
