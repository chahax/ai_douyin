"""Current complete source rows only; no future framing/whole-film metadata in media prompt."""
from copy import deepcopy
import math,re
from src.content_factory.creative_stage_contracts import digest
MODEL='doubao-seedance-2-0-mini-260615'
STATE_KEYS={'badge_location':'工牌','paper_location':'纸位置','paper_facing':'纸朝向','paper_signed':'纸签名','pen_location':'笔位置','folder_location':'文件夹','zhou_position':'周姐','xiaolin_position':'小林','xiaolin_hands':'小林双手'}
STATE_VALUES={'xiaolin_neck':'一直戴在小林胸前','zhou_table_side':'周姐一侧桌面','table_middle':'两人之间桌面中央','zhou_folder':'周姐文件夹内','face_up':'印字面朝上','inside_folder':'夹内','unsigned':'没有签名','zhou_carried':'周姐抱着','seated_opposite':'对面坐着','standing':'站在桌旁','outside_room':'已在门外','seated':'坐在原椅上','table_edge':'在桌沿','knees_tense':'在膝上尚紧','knees_relaxed':'在膝上已松开'}

def project(compiled):
 if not compiled['complete'] or compiled['total_duration_seconds']>180:raise ValueError('complete short schedule required')
 groups=[];current=[];total=0
 for row in compiled['schedule']:
  duration=row['end']-row['start']
  if duration<=0 or duration>15:raise ValueError('cannot split/rewrite a source step to fit service')
  if current and (current[-1]['shot_id']!=row['shot_id'] or total+duration>15+1e-6):
   groups.append(current);current=[];total=0
  current.append(deepcopy(row));total+=duration
 if current:groups.append(current)
 result=[]
 for i,rows in enumerate(groups):
  seconds=sum(r['end']-r['start'] for r in rows);duration=max(4,math.ceil(round(seconds,6)))
  result.append({'segment_id':f'SHORT{i+1:02}','shot_id':rows[0]['shot_id'],'source_refs':[r['source_ref'] for r in rows],'rows':rows,'source_seconds':round(seconds,6),'duration_seconds':duration,'time_scale':duration/seconds,'image_role':'reference_image' if i==0 else 'first_frame'})
 if sum(d['duration_seconds'] for d in result)>179:raise ValueError('integer service runtime leaves less than1s assembly margin under180; revise performance')
 if [r for d in result for r in d['source_refs']]!=[r['source_ref'] for r in compiled['schedule']]:raise ValueError('source coverage changed')
 return result

def prose(value,all_speech,current_speech=None):
 if not isinstance(value,str) or not value.strip():raise ValueError('missing model acting')
 original=value
 # Whole source speech is never split. Only an exact copy of CURRENT source
 # utterance in a delivery cue is labelled as a reference, not spoken again.
 # This is wire serialization; stored original performance remains byte-exact.
 if current_speech:
  core=current_speech.rstrip('。！？!?')
  pattern=re.compile(r'(?:\\*["“「])?'+re.escape(core)+r'[。！？!?]?(?:\\*["”」])?')
  value=pattern.sub('本句',value)
 for line in all_speech:
  if line.rstrip('。！？!?') in value:raise ValueError('non-current or unresolved full speech leaked into acting')
 if any(x in value for x in ('$text','state_changes','source_ref')):raise ValueError('internal protocol leaked into model performance')
 return value

def render_prompt(definition,all_speech):
 d=definition;start=d['rows'][0]['start_state'];scale=d['time_scale'];clock=0
 lines=[f"{d['duration_seconds']}秒，9:16竖屏，中国当代普通公司写实短片，自然室内日光，克制但可读的表演。",
  '参考中的同一位男员工小林与同一位女人事周姐，保持脸、年龄、发型和服装；只有两人，不增加同事、分身或路人。',
  '同一间玻璃隔断会议室、深色长方形桌、两张对坐椅、原来的同一扇门。固定两人中近景，脸、桌面和门侧关系可读；全段单个连续镜头，不切场、不换办公室。',
  '仅执行下面时间表，动作说明是给演员的指令，不朗读。对白只在标有“对白”的位置说一次，用自然清晰中文普通话，不翻译、无旁白、无配乐。',
  '无字幕、屏幕台词、姓名标签、标题或文字贴纸；只有剧情纸张本来的印字可以出现。',
  '当前起态：'+'；'.join(STATE_KEYS[k]+'：'+STATE_VALUES[v] for k,v in start.items())+'。']
 if d['image_role']=='reference_image':
  lines+=['图片1仅作为这两个人的身份、服装和这间会议室的空间光线参考；重新构图建立上述起态。旧图中的工牌放桌上和纸正面朝下不沿用，新片开场工牌已经戴好，不演摘戴；文件夹初始敞开，纸与笔摆在周姐一侧。纸是未签的《自愿离职申请》，原因栏印着“个人原因”。']
 else:lines+=['严格从输入的上一段服务原始尾帧接着演，沿用其人物、服装、构图、站位和桌面；不重复上段已说台词与动作。']
 for row in d['rows']:
  phases=[('before',row['active_start']-row['start'],row['before_performance']),('active',row['active_end']-row['active_start'],row['active_performance']),('after',row['end']-row['active_end'],row['after_performance'])]
  for phase,seconds,acting in phases:
   if seconds<=1e-9:continue
   end=clock+seconds*scale;at=f'{clock:.2f}–{end:.2f}秒：';cue=prose(acting,all_speech,row['original_text'] if phase=='active' and row['source_kind']=='dialogue' else None)
   if phase=='active' and row['source_kind']=='dialogue':
    speaker=row['speaker'].split('（')[0];lines.append(at+speaker+'对白：「'+row['original_text']+'」。'+cue+' 对方只倾听，不跟读。')
   else:lines.append(at+('无声准备：' if phase=='before' else '无声反应：' if phase=='after' else '无对白动作：')+cue)
   clock=end
 if not any(r['source_kind']=='dialogue' for r in d['rows']):lines.append('本段全程不说话、不念纸上字，只保留环境和动作声。')
 if d['rows'][-1]['end_state']['zhou_position']=='outside_room':lines.append('周姐已经独自出门，小林留在原椅；不要让小林起身、不要重复进出门。')
 lines.append('每件原动作只做一次。停止在当前步骤完成处，不预演下一段。工牌全程戴着、纸不签名。')
 prompt='\n'.join(lines)
 for text in all_speech:
  expected=sum(r['source_kind']=='dialogue' and r['original_text']==text for r in d['rows'])
  if prompt.count(text)!=expected:raise ValueError('current unique speech scope violated')
 return prompt
