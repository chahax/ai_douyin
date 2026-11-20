import bpy,json
from pathlib import Path
r=Path('D:/IT/ai_douyin/tools/scene_lab_20261006/geometry')
m=json.loads((r/'SCENE_MANIFEST.json').read_text());bpy.context.view_layer.update();bad=[]
for entry in m['objects']:
 o=bpy.data.objects.get(entry['name'])
 if o is None or max(abs(o.matrix_world[i][j]-entry['world_matrix'][i][j]) for i in range(4) for j in range(4))>1e-5:bad.append(entry['name'])
checks={'manifest_matches_saved_world_transforms':not bad,'mismatched_objects':bad,'desks':len([o for o in bpy.data.objects if o.name in ['E01_desk','E02_desk']]),'chairs':len([o for o in bpy.data.objects if o.name in ['E09_seat','E10_seat']]),'door_leaf_count':len([o for o in bpy.data.objects if o.name=='E04_door_leaf']),'single_contiguous_floor':bpy.data.objects.get('E07_continuous_floor') is not None,'door_opening_between_office_and_corridor':abs(bpy.data.objects['E04_door_hinge'].location.y-5)<1e-6 and abs((bpy.data.objects['E08_far_wall_right'].location.x-bpy.data.objects['E08_far_wall_right'].dimensions.x/2)-(bpy.data.objects['E08_far_wall_left'].location.x+bpy.data.objects['E08_far_wall_left'].dimensions.x/2)-.95)<1e-5 and bpy.data.objects['E07_continuous_floor'].dimensions.y>6.9,'all_camera_manifests_bind_same_geometry':len({c['geometry_sha256'] for c in m['cameras']})==1,'human_layout_approved':None,'creative_quality_approved':None}
(r/'GEOMETRY_CHECKS.json').write_text(json.dumps(checks,indent=2),encoding='utf-8');print(json.dumps(checks))
