"""One explicit local MoGe inference with existing GPU leases and CPU exports."""
from pathlib import Path
import argparse,hashlib,json,os,sys,time,urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
BASE=ROOT/'data/tools/spatial_20261107'
for key in ('TEMP','TMP','TORCH_HOME','HF_HOME','XDG_CACHE_HOME','MPLCONFIGDIR','CUDA_CACHE_PATH'):
 value=BASE/'cache'/key.lower();value.mkdir(parents=True,exist_ok=True);os.environ[key]=str(value)
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1')
def sha(p):return hashlib.file_digest(Path(p).open('rb'),'sha256').hexdigest()
def write(p,v):Path(p).write_text(json.dumps(v,indent=2),encoding='utf-8')
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
 if (out/'CLAIM.json').exists():raise RuntimeError('preserve original inference; do not repeat existing claim')
 checkpoint=ROOT/'data/models/spatial_20261107/moge-2-vits-normal/model.pt'
 expected='79a16621928c2bf0ed04659218c55c01075e950507f40bb3332fb4c873d3e1dc'
 if sha(checkpoint)!=expected:raise ValueError('official model hash changed')
 source_sha=sha(args.source)
 import cv2,numpy as np,torch
 from moge.model.v2 import MoGeModel
 from src.content_factory import visual_h3_handoff_v3 as native
 plan=json.loads((ROOT/'data/video_generation/visual_h3_ref_v20/seedance_reference_S01_736_20261107_v1/PLAN.json').read_text(encoding='utf-8'))
 image=cv2.cvtColor(cv2.imread(str(args.source)),cv2.COLOR_BGR2RGB);h,w=image.shape[:2];scale=min(1,768/max(h,w));image=cv2.resize(image,(round(w*scale),round(h*scale)),interpolation=cv2.INTER_AREA)
 started=time.time();timing={}
 with native._gpu(plan):
  with urllib.request.urlopen('http://127.0.0.1:8190/queue',timeout=10) as r:q=json.load(r)
  if q['queue_running'] or q['queue_pending']:raise RuntimeError('GPU queue busy, no inference claim')
  write(out/'CLAIM.json',dict(pid=os.getpid(),time=started,source=str(args.source.resolve()),source_sha256=source_sha,checkpoint=str(checkpoint),checkpoint_sha256=expected,one_call=True))
  print('GPU_LEASE_ACQUIRED',time.time(),flush=True)
  torch.cuda.reset_peak_memory_stats();t=time.perf_counter();model=MoGeModel.from_pretrained(str(checkpoint)).to('cuda').eval();torch.cuda.synchronize();timing['load_seconds']=time.perf_counter()-t
  tensor=torch.tensor(image/255,dtype=torch.float32,device='cuda').permute(2,0,1);t=time.perf_counter()
  with torch.inference_mode():raw=model.infer(tensor,resolution_level=5,use_fp16=True)
  torch.cuda.synchronize();timing['inference_seconds']=time.perf_counter()-t;timing['peak_allocated_bytes']=torch.cuda.max_memory_allocated();timing['peak_reserved_bytes']=torch.cuda.max_memory_reserved()
  arrays={k:v.detach().float().cpu().numpy() for k,v in raw.items() if isinstance(v,torch.Tensor)}
  del raw,tensor,model;torch.cuda.empty_cache();print('GPU_LEASE_RELEASED',time.time(),flush=True)
 # Everything after this line is CPU-only; raw inference survives export failure.
 np.savez_compressed(out/'geometry.npz',**arrays);cv2.imwrite(str(out/'source.png'),cv2.cvtColor(image,cv2.COLOR_RGB2BGR))
 depth=arrays['depth'];mask=arrays['mask'].astype(bool);finite=mask&np.isfinite(depth);lo,hi=np.percentile(depth[finite],[2,98]);vis=np.clip((depth-lo)/max(hi-lo,1e-8),0,1);vis[~finite]=0
 cv2.imwrite(str(out/'DEPTH.png'),cv2.applyColorMap((vis*255).astype(np.uint8),cv2.COLORMAP_TURBO));cv2.imwrite(str(out/'mask.png'),mask.astype('uint8')*255)
 if 'normal' in arrays:cv2.imwrite(str(out/'NORMAL.png'),cv2.cvtColor(((arrays['normal']*.5+.5).clip(0,1)*255).astype('uint8'),cv2.COLOR_RGB2BGR))
 camera=dict(intrinsics_normalized=arrays['intrinsics'].tolist(),coordinate_system='OpenCV: x right, y down, z forward; exported GLB flips y,z',source_size=[w,h],inference_size=list(image.shape[1::-1]),estimated_geometry=True,unseen_region_reconstructed=False)
 write(out/'CAMERA.json',camera)
 receipt=dict(status='inference_complete',model='MoGe-2-vits-normal',source=dict(path=str(args.source.resolve()),sha256=source_sha),weight=dict(path=str(checkpoint),sha256=expected),timing=timing,valid_pixel_fraction=float(finite.mean()),output_size=list(image.shape[1::-1]),production_approved=False,full_room_reconstruction=False)
 write(out/'INFERENCE_RESULT.json',receipt)
 t=time.perf_counter();import utils3d_moge as utils3d
 from moge.utils.io import save_glb,save_ply
 clean=finite&~utils3d.np.depth_map_edge(depth,rtol=.04)
 normal=arrays.get('normal');maps=[arrays['points'],image.astype(np.float32)/255,utils3d.np.uv_map(*depth.shape)]
 if normal is not None:maps.append(normal)
 mesh=utils3d.np.build_mesh_from_map(*maps,mask=clean,tri=True)
 faces,vertices,colors,uv=mesh[:4];normals=mesh[4] if len(mesh)>4 else None
 vertices=vertices*[1,-1,-1];uv=uv*[1,-1]+[0,1]
 if normals is not None:normals=normals*[1,-1,-1]
 save_glb(out/'mesh.glb',vertices,faces,uv,image,normals);save_ply(out/'pointcloud.ply',vertices,np.zeros((0,3),dtype=np.int32),colors,normals)
 receipt['status']='export_complete';receipt['timing']['cpu_export_seconds']=time.perf_counter()-t;receipt['files']=[dict(path=str(x),sha256=sha(x),bytes=x.stat().st_size) for x in sorted(out.iterdir()) if x.is_file() and x.name!='INFERENCE_RESULT.json'];write(out/'INFERENCE_RESULT.json',receipt);print(json.dumps(receipt),flush=True)
if __name__=='__main__':main()
