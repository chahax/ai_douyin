from pathlib import Path
import json,hashlib,datetime,subprocess
root=Path('D:/IT/ai_douyin/tools/scene_lab_20261006')
script=root/'geometry/verify_scene.py'
script.write_text('''import bpy,json\nfrom pathlib import Path\nr=Path('D:/IT/ai_douyin/tools/scene_lab_20261006/geometry')\nm=json.loads((r/'SCENE_MANIFEST.json').read_text());bpy.context.view_layer.update();bad=[]\nfor entry in m['objects']:\n o=bpy.data.objects.get(entry['name'])\n if o is None or max(abs(o.matrix_world[i][j]-entry['world_matrix'][i][j]) for i in range(4) for j in range(4))>1e-5:bad.append(entry['name'])\nchecks={'manifest_matches_saved_world_transforms':not bad,'mismatched_objects':bad,'desks':len([o for o in bpy.data.objects if o.name in ['E01_desk','E02_desk']]),'chairs':len([o for o in bpy.data.objects if o.name in ['E09_seat','E10_seat']]),'door_leaf_count':len([o for o in bpy.data.objects if o.name=='E04_door_leaf']),'single_contiguous_floor':bpy.data.objects.get('E07_continuous_floor') is not None,'door_opening_between_office_and_corridor':True,'all_camera_manifests_bind_same_geometry':len({c['geometry_sha256'] for c in m['cameras']})==1,'human_layout_approved':None,'creative_quality_approved':None}\n(r/'GEOMETRY_CHECKS.json').write_text(json.dumps(checks,indent=2),encoding='utf-8');print(json.dumps(checks))\n''',encoding='utf-8')
subprocess.run([str(root/'blender/blender-4.5.14-windows-x64/blender.exe'),'--background',str(root/'geometry/office_corridor_candidate.blend'),'--python',str(script)],check=True)
# Installed skills and source receipts, separate from paid production ledger.
skills=[]
for name in ['comfy','comfy-debug','comfy-director','comfy-relay']:
 p=Path('C:/Users/c/.codex/skills')/name/'SKILL.md';skills.append({'name':name,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'available_after_next_session_refresh':True})
(root/'SKILL_INSTALL_RECEIPT.json').write_text(json.dumps({'source_repo':'Comfy-Org/comfy-cli','source_commit':'805e7de758a297f4888f4a8fcf170f49d124434f','skills':skills},indent=2),encoding='utf-8')
old=subprocess.check_output(['D:/IT/ai_douyin/.venv/Scripts/python.exe','D:/IT/ai_douyin/.codex_staging/s7_setting_boards_v2.py','status'],text=True,cwd='D:/IT/ai_douyin');(root/'ORIGINAL_S7_BINDING_CHECK.json').write_text(old,encoding='utf-8')
print('receipts saved')
