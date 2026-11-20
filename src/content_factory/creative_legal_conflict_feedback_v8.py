"""Make the short-utterance constraint explicit in the actual tool schema."""
from copy import deepcopy
import json
from src.content_factory.creative_legal_conflict_feedback_v7 import build_wire as prior,validate_current_script
from scripts.creative_resume_dispatch_v3 import digest
def build_wire(*args,**kwargs):
 req=prior(*args,**kwargs)
 if args[4]=='draft':
  beats=req['structured_schema']['properties']['beats']
  shapes=[beats['items']]+beats.get('prefixItems',[])
  for beat in shapes:
   step=beat['properties']['steps']['items']
   for branch in step['allOf']:
    if branch['if']['properties']['kind'].get('const')=='dialogue':
     branch['then']['properties']['text']={'type':'string','minLength':1,'maxLength':40,'description':'普通话完整短句，含标点最多40字符，每句一个主要意思，不长篇复述公司口径。'}
  req['messages'][0]['content']+='实际工具Schema每句含标点最多40字符，务必逐句满足。尤其人事答个人原因时只讲公司要求这一件事，不再接一整段模板口径经办上交的同義复述。第二轮改为短的个人劝说；小林正面回应能理解她却不能签成自己辞职。完整新稿不截断上一稿长句，不用假省略号。'
  ctx=json.loads(req['messages'][1]['content'])
  ctx['short_speech_tool_contract']={'dialogue_text_max_characters_including_punctuation':40,'one_principal_idea_per_utterance':True,'complete_model_rewrite_not_trimming_source':True}
  req['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False);req['input_provenance']['source_context_sha256']=digest(ctx)
 req['operator_version']='legal_conflict_feedback_complete_revision/v8_short_speech_tool_schema'
 return req

