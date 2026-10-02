from pathlib import Path
import os,sys,socket,json,hashlib
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path.insert(0,str(ROOT));os.environ['LLM_PROVIDER']='mock';os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'integrity_runtime.sqlite3').replace('\\','/')
def blocked(*args,**kwargs):raise RuntimeError('Integrity verification forbids networking')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
from scripts.manage_creative_governance import verify
from alembic.config import Config
from alembic.script import ScriptDirectory
v18=ROOT/'data/creative_governance/20261002_v18_platform_refactor';v17=ROOT/'data/creative_governance/20261001_v17_history_usage'
result=verify(v18)
upgrade=json.loads((v18/'runtime_upgrade_receipt.json').read_text(encoding='utf-8'))
manifest=json.loads((v17/'artifact_manifest.json').read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
bad=[row['path'] for row in manifest['artifacts'] if sha(v17/row['path'])!=row['sha256']]
from src.content_factory import creative_governed_runtime
answer={'v18_runtime_and_artifacts_valid':True,'runtime_verification':result['runtime_sources'],'v18_dataset':result['dataset'],'v17_frozen_artifact_failures':bad,'v17_manifest_matches_upgrade_base':sha(v17/'artifact_manifest.json')==upgrade['base_artifact_manifest_sha256'],'alembic_heads':list(ScriptDirectory.from_config(Config(str(ROOT/'alembic.ini'))).get_heads()),'configured_governance_directory':creative_governed_runtime.REGISTRY_DIRECTORY}
(OUT/'governance_and_migrations.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(answer,ensure_ascii=False))
