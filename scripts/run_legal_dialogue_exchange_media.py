"""Strict media-only adapter for frozen reusable dialogue text runs."""
from pathlib import Path
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts.run_legal_dialogue_exchange import Exchange,contract,control,sha

class MediaExchange(Exchange):
 def media_plan(self,client):
  x=control.read(self.root/'INPUT.json');g=control.read(self.root/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json');c=self.compiled()
  if not g['text_sample_qualified'] or g['unresolved_mandatory_findings'] or g['source_sha256']!=contract.digest(x['background_full_script']) or g['compiled_sha256']!=contract.digest(c):
   raise ValueError('independent current media gate unresolved')
  p=super().media_plan(client)
  adapter=Path(__file__).resolve();p['sources'][str(adapter.relative_to(PROJECT))]={'path':str(adapter),'sha256':sha(adapter)}
  p['independent_current_gate_verified']=True
  return p

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('run_dir');ap.add_argument('operation',choices=['media_prepare','media_submit','media_query']);a=ap.parse_args()
 print(json.dumps(MediaExchange(a.run_dir).media(a.operation),ensure_ascii=False),flush=True)
