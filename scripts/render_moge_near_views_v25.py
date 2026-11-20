"""One bounded CPU-only view-synthesis demonstration of an existing MoGe mesh.

This does not invoke MoGe, fill unseen geometry or join the staged room's axes.
It emits an original camera view and +/-0.03 estimated-unit lateral views.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw

PROJECT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def binding(path):return {'path':str(Path(path).resolve()),'sha256':sha(path)}


SCRIPT=r'''import bpy,json,math,hashlib
from pathlib import Path
from mathutils import Vector
root=Path(__ROOT__);out=Path(__OUT__);camera_info=json.loads((root/'CAMERA.json').read_text(encoding='utf-8'))
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=str(root/'mesh.glb'))
meshes=[o for o in bpy.data.objects if o.type=='MESH'];assert meshes
textures=[]
for obj in meshes:
 for mat in obj.data.materials:
  mat.use_nodes=True;nodes=mat.node_tree.nodes;links=mat.node_tree.links
  images=[n for n in nodes if n.type=='TEX_IMAGE' and n.image]
  assert images,'Imported mesh has no image texture; stop rather than invent color.'
  tex=images[0];textures.append(tex.image.name);emission=nodes.new('ShaderNodeEmission');emission.inputs['Strength'].default_value=1
  output=next(n for n in nodes if n.type=='OUTPUT_MATERIAL')
  for link in list(output.inputs['Surface'].links):links.remove(link)
  links.new(tex.outputs['Color'],emission.inputs['Color']);links.new(emission.outputs[0],output.inputs['Surface']);mat.use_backface_culling=False
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=1
scene.render.resolution_x=576;scene.render.resolution_y=768;scene.render.resolution_percentage=100;scene.render.film_transparent=True;scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA'
scene.view_settings.view_transform='Standard';scene.view_settings.look='None';scene.view_settings.exposure=0;scene.view_settings.gamma=1
bpy.ops.object.camera_add(location=(0,0,0),rotation=(math.pi/2,0,0));camera=bpy.context.object;scene.camera=camera
intr=camera_info['intrinsics_normalized'];assert abs(intr[0][2]-.5)<1e-6 and abs(intr[1][2]-.5)<1e-6
camera.data.type='PERSP';camera.data.sensor_fit='VERTICAL';camera.data.sensor_height=24;camera.data.lens=intr[1][1]*24;camera.data.clip_start=.001;camera.data.clip_end=10000
views=[]
for name,x in [('center',0),('left',-.03),('right',.03)]:
 camera.location=(x,0,0);scene.render.filepath=str(out/(name+'.png'));bpy.ops.render.render(write_still=True)
 p=camera.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(),x=576,y=768)
 views.append({'id':name,'translation_estimated_units':[x,0,0],'camera_world_matrix':[list(r) for r in camera.matrix_world],'projection_matrix':[list(r) for r in p],'image':str(out/(name+'.png'))})
value={'schema':'moge_actual_near_views/v25','engine':scene.render.engine,'device':scene.cycles.device,'blender_version':bpy.app.version_string,'textures':textures,'view_transform':scene.view_settings.view_transform,'views':views,'mesh_objects':[o.name for o in meshes],'estimated_geometry':True,'unseen_geometry_filled':False,'full_room_reconstruction':False,'coordinate_conversion':'Existing exporter OpenCV xyz -> GLB x,-y,-z; Blender import applies glTF Y-up to Z-up. Camera origin looks +Y with +Z up.','production_approved':False}
(out/'RENDER_METADATA.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');print('MOGE_CPU_NEAR_VIEWS_COMPLETE')
'''


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=PROJECT/'data/video_generation/spatial_minute_experiments_20261107_v1/moge');p.add_argument('--blender',type=Path,required=True);args=p.parse_args();root=args.root.resolve();out=root/'near_views';out.mkdir(exist_ok=True)
    inputs=[root/name for name in ('mesh.glb','CAMERA.json','source.png','INFERENCE_RESULT.json')];assert all(f.is_file() for f in inputs)
    script=out/'render_near_views.py';text=SCRIPT.replace('__ROOT__',repr(str(root))).replace('__OUT__',repr(str(out)))
    if script.exists() and script.read_text(encoding='utf-8')!=text:raise ValueError('Existing near-view script changed; preserve original attempt')
    script.write_text(text,encoding='utf-8');request={'schema':'moge_near_view_request/v25','sources':[binding(f) for f in inputs],'script':binding(script),'blender':binding(args.blender),'translations_estimated_units':[0,-.03,.03],'device':'CPU','max_attempts':1,'production_approved':False}
    request_file=out/'REQUEST.json'
    if request_file.exists():raise ValueError('Bounded near-view request already exists; do not automatically retry')
    request_file.write_text(json.dumps(request,indent=2)+'\n',encoding='utf-8')
    try:
        with (out/'stdout.log').open('w',encoding='utf-8') as stdout,(out/'stderr.log').open('w',encoding='utf-8') as stderr:
            process=subprocess.run([str(args.blender),'--background','--factory-startup','--threads','2','--python',str(script)],stdout=stdout,stderr=stderr,timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        assert process.returncode==0 and 'MOGE_CPU_NEAR_VIEWS_COMPLETE' in (out/'stdout.log').read_text(encoding='utf-8')
        metadata=json.loads((out/'RENDER_METADATA.json').read_text(encoding='utf-8'));assert metadata['device']=='CPU' and len(metadata['views'])==3
        source=Image.open(root/'source.png').convert('RGB').resize((576,768));cards=[];stats=[]
        for name in ('source','center','left','right'):
            if name=='source':im=source.copy()
            else:
                actual=Image.open(out/(name+'.png')).convert('RGBA');assert actual.size==(576,768)
                alpha=list(actual.getchannel('A').getdata());valid=sum(v>250 for v in alpha)/len(alpha);bg=Image.new('RGB',actual.size,'#aa55aa');bg.paste(actual,mask=actual.getchannel('A'));im=bg
                item={'view':name,'opaque_fraction':valid,'holes_fraction':1-valid,'holes_shown_magenta':True}
                if name=='center':
                    pairs=zip(list(source.getdata()),list(actual.convert('RGB').getdata()),alpha);sums=[sum(abs(a-b) for a,b in zip(rgb,render))/3 for rgb,render,a in pairs if a>250]
                    item['center_source_mean_absolute_error_0_255']=sum(sums)/max(1,len(sums))
                stats.append(item)
            card=Image.new('RGB',(288,410),'white');card.paste(im.resize((288,384)),(0,26));ImageDraw.Draw(card).text((4,5),name+' / estimated near view',fill='black');cards.append(card)
        board=Image.new('RGB',(1152,410),'white')
        for i,card in enumerate(cards):board.paste(card,(i*288,0))
        board.save(out/'CONTACT.jpg',quality=94)
        center=next(x for x in stats if x['view']=='center');aligned=center['opaque_fraction']>.90 and center['center_source_mean_absolute_error_0_255']<25
        result={'schema':'moge_near_views_result/v25','status':'near_views_rendered_alignment_plausible' if aligned else 'rendered_alignment_unconfirmed_do_not_use','request':binding(request_file),'metadata':binding(out/'RENDER_METADATA.json'),'files':[binding(out/(n+'.png')) for n in ('center','left','right')],'contact':binding(out/'CONTACT.jpg'),'statistics':stats,'estimated_geometry':True,'unseen_geometry_filled':False,'metric_scale_measured':False,'nominal_translation':'.03 model estimated units; approximately3cm only if metric estimate is accurate, not physically calibrated','does_not_share_staged_room_coordinates':True,'automatically_added_to_video_references':False,'gpu_inference_calls':0,'model_posts':0,'production_approved':False}
        for f in request['sources']:assert sha(f['path'])==f['sha256']
        (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
    except Exception as e:
        (out/'ERROR.json').write_text(json.dumps({'status':'bounded_attempt_stopped','error_type':type(e).__name__,'error':str(e),'automatic_retry':False,'production_approved':False},indent=2)+'\n',encoding='utf-8');raise


if __name__=='__main__':main()
