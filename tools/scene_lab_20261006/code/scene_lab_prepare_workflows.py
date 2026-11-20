from pathlib import Path
import json,shutil,hashlib,datetime
root=Path('tools/scene_lab_20261006').resolve();out=root/'comfy';info=json.loads((out/'object_info.json').read_text())
# Inputs copied from own deterministic geometry, not from a generated video.
for view in ['office_to_door','corridor_to_office']:
 for suffix in ['.png','_depth_0001.png']:shutil.copy2(root/'geometry'/(view+suffix),out/'input'/(view+suffix))
def graph(view,length,video):
 def n(c,**inputs):return {'class_type':c,'inputs':inputs}
 g={'1':n('UNETLoader',unet_name='wan2.1_vace_1.3B_fp16.safetensors',weight_dtype='default'),
 '2':n('CLIPLoader',clip_name='umt5_xxl_fp8_e4m3fn_scaled.safetensors',type='wan',device='default'),
 '3':n('VAELoader',vae_name='wan_2.1_vae.safetensors'),
 '4':n('CLIPTextEncode',clip=['2',0],text='Photorealistic small contemporary office connected to a plain corridor through one doorway. The camera is locked. Two pale wood desks, two black office chairs, a pale wood drawer cabinet, off-white plaster walls, gray matte flooring, a wide gray-blinded window, warm evening light from the window. Preserve the reference room layout, doorway position and perspective. Empty room, no people. Subtle natural light, realistic surface textures.'),
 '5':n('CLIPTextEncode',clip=['2',0],text='people, faces, extra doorways, extra windows, moving camera, rearranged furniture, cartoon, illustration, text, watermark, distorted architecture'),
 '6':n('LoadImage',image=view+'_depth_0001.png'),
 '7':n('RepeatImageBatch',image=['6',0],amount=length),
 '8':n('LoadImage',image=view+'.png'),
 '9':n('ModelSamplingSD3',model=['1',0],shift=8.0),
 '10':n('WanVaceToVideo',positive=['4',0],negative=['5',0],vae=['3',0],width=512,height=288,length=length,batch_size=1,strength=1.0,control_video=['7',0],reference_image=['8',0]),
 '11':n('KSampler',model=['9',0],seed=20261006,steps=20,cfg=5.0,sampler_name='euler',scheduler='simple',positive=['10',0],negative=['10',1],latent_image=['10',2],denoise=1.0),
 '12':n('TrimVideoLatent',samples=['11',0],trim_amount=['10',3]),
 '13':n('VAEDecode',samples=['12',0],vae=['3',0])}
 if video:g.update({'14':n('CreateVideo',images=['13',0],fps=8.0),'15':n('SaveVideo',video=['14',0],filename_prefix='scene_lab/depth_'+view,format='mp4',codec='h264')})
 else:g['14']=n('SaveImage',images=['13',0],filename_prefix='scene_lab/depth_'+view)
 assert all(x['class_type'] in info and not info[x['class_type']].get('api_node') for x in g.values())
 return g
(out/'workflows').mkdir(exist_ok=True)
items=[]
for name,view,length,video in [('still_office','office_to_door',1,False),('still_corridor','corridor_to_office',1,False),('short_video_office','office_to_door',17,True)]:
 p=out/'workflows'/(name+'.json');p.write_text(json.dumps(graph(view,length,video),indent=2),encoding='utf-8');items.append({'id':name,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'length':length,'kind':'video' if video else 'image'})
(out/'EXPERIMENT_CONTRACT.json').write_text(json.dumps({'user_authorization':'都下载下来组合试下','planned_jobs':items,'max_local_jobs':3,'paid_cloud_calls':0,'automatic_retry':False,'production_script_modified':False,'identity_selected':None,'video_review':'awaiting_human_review_after_save','purpose':'local geometry-to-depth-to-VACE compatibility and human visual comparison'},indent=2),encoding='utf-8')
print(json.dumps(items))
