from pathlib import Path
import json,hashlib
base=Path('data/production_trials/reusable_20260927');lib=json.loads(Path('data/visual_asset_library/reusable_assets.json').read_text(encoding='utf-8-sig'))
notes={
'CHENMO_THREE_VIEW':{'observed':'同一成年男性正侧背三视图，短黑发、深灰夹克、蓝灰内衫、黑裤，无围裙；中性背景柔光，面部和全身可读。','reference_usable':True,'initial_story_compatible':False,'reason':'初稿要求工作围裙，原图没有。'},
'LINYU_THREE_VIEW_V3':{'observed':'成年女性正侧背三视图，齐肩黑发，米白针织开衫、橄榄色内衫、深色裤、黑色平底鞋；面部与服装连续可读。','reference_usable':True,'initial_story_compatible':True,'reason':'浅色外套与中长发方向兼容，额外必需检索标签导致路由拒绝。'},
'STUDIO_DAY_PHOTOREAL':{'observed':'左上窗提供柔和日光，右后门，前景大桌与椅子遮挡后方地面；后方有多架画架和小木凳。','reference_usable':True,'initial_story_compatible':False,'reason':'不能证明初稿左后门、右后窗台以及画架两侧畅通，须调整分镜或另做适配场景。'}}
rows=[]
for a in lib['assets']:
 if a['reuse_key'] in notes: rows.append({'reuse_key':a['reuse_key'],'image':a['image'],**notes[a['reuse_key']]})
(base/'ASSET_VISUAL_OBSERVATIONS.json').write_text(json.dumps({'schema':'trial_actual_asset_observations/v1','method':'assistant_viewed_original_images','assets':rows,'is_style_gate_pass':False,'video_or_audio_review_performed':False},ensure_ascii=False,indent=2),encoding='utf-8')
run=Path('data/creative_workflows/reusable_trial_20260927');state=json.loads((run/'state.json').read_text(encoding='utf-8'));print(json.dumps({k:state.get(k) for k in ('status','calls_started','reported_tokens','revision_rounds','assistant_revision_status','contract_repairs_used')},ensure_ascii=False))
for p in sorted(run.glob('*assistant_02*.json')):
 d=json.loads(p.read_text(encoding='utf-8'));print(p.name,d.get('status'),d.get('error'))
