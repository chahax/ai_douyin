"""Read-only native validation diagnostic, never executes or submits media nodes."""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'data/qa/h3_validation_timeout_20261102'
RUN.mkdir(parents=True, exist_ok=True)
COMFY = Path('D:/IT/AI_vido/ComfyUI')
SERVICE = ROOT / 'data/video_generation/h3_six_children_s01_720p_20261102'
GRAPH = ROOT / 'data/video_generation/h3_six_children_60s_20261102/S02/workflow_api.json'
VALIDATOR = ROOT / 'data/video_generation/h3_assistant_screenplay_full_20261016/runtime/validate_graph.py'
wrapper = RUN / 'trace_validation.py'
wrapper.write_text("import faulthandler,runpy\nfaulthandler.enable()\nfaulthandler.dump_traceback_later(30, repeat=True)\nrunpy.run_path(" + repr(str(VALIDATOR)) + ",run_name='__main__')\n", encoding='utf-8')
env = os.environ.copy()
env.update(json.loads((SERVICE / 'SERVER_STARTED.json').read_text(encoding='utf-8'))['cache_env'])
env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONIOENCODING='utf-8')
command = [str(COMFY / '.venv/Scripts/python.exe'), '-B', '-u', str(wrapper), '--graph', str(GRAPH),
           '--report', str(RUN / 'NATIVE_VALIDATION.json'), '--input-root', str(SERVICE / 'input')]
record = dict(command=command, cwd=str(COMFY), start=time.time(), report=str(RUN / 'NATIVE_VALIDATION.json'))
(RUN / 'START.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
with (RUN / 'stdout.log').open('wb') as out, (RUN / 'stderr.log').open('wb') as err:
    result = subprocess.run(command, stdout=out, stderr=err, cwd=COMFY, env=env, timeout=600)
record.update(returncode=result.returncode, elapsed=time.time()-record['start'])
(RUN / 'END.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
print(json.dumps(record), flush=True)
