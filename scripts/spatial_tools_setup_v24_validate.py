"""Read-only structural validation of one saved MoGe experiment, no inference."""
from pathlib import Path
import argparse,hashlib,json
import numpy as np
def sha(p):return hashlib.file_digest(Path(p).open('rb'),'sha256').hexdigest()
def validate(root):
 root=Path(root).resolve();r=json.loads((root/'INFERENCE_RESULT.json').read_text())
 if r['status']!='export_complete' or r['full_room_reconstruction'] is not False or r['production_approved'] is not False:raise ValueError('must remain estimated single-view geometry')
 for f in [r['source'],r['weight'],*r['files']]:
  if sha(f['path'])!=f['sha256']:raise ValueError('artifact digest mismatch '+f['path'])
 with np.load(root/'geometry.npz') as z:
  points=z['points'];depth=z['depth'];mask=z['mask'].astype(bool);k=z['intrinsics']
  if points.shape!=(*depth.shape,3) or mask.shape!=depth.shape or k.shape!=(3,3):raise ValueError('map/camera shape mismatch')
  if list(depth.shape[::-1])!=r['output_size']:raise ValueError('output geometry size changed')
  if not np.isfinite(points[mask]).all() or not np.isfinite(depth[mask]).all() or not (depth[mask]>0).all():raise ValueError('invalid observed geometry')
  if k[0,0]<=0 or k[1,1]<=0 or not np.allclose(k[2],[0,0,1]):raise ValueError('camera matrix invalid')
  valid_fraction=float(mask.mean());depth_range=[float(depth[mask].min()),float(depth[mask].max())]
 import trimesh
 mesh=trimesh.load(root/'mesh.glb',force='scene')
 if not mesh.geometry:raise ValueError('GLB empty')
 for g in mesh.geometry.values():
  if len(g.vertices)<3 or len(g.faces)<1 or not np.isfinite(g.vertices).all():raise ValueError('mesh invalid')
 return dict(status='cpu_structure_validation_passed',source_sha256=r['source']['sha256'],result_sha256=sha(root/'INFERENCE_RESULT.json'),valid_pixel_fraction=valid_fraction,depth_range=depth_range,glb_geometry_count=len(mesh.geometry),production_approved=False,unseen_region_validation=False,model_inference_calls=0)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args();r=validate(args.root);(args.root/'CPU_VALIDATION.json').write_text(json.dumps(r,indent=2),encoding='utf-8');print(json.dumps(r))
