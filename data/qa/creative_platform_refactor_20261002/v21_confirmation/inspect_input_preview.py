from pathlib import Path
import os,sys,json,socket,subprocess,ast
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'ui_inventory.sqlite3').replace(chr(92),'/')
os.environ['LLM_PROVIDER']='mock'
def blocked(*a,**kw):raise RuntimeError('P1 input preview inventory prohibits networking')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
from streamlit.testing.v1 import AppTest
from src.web import creative_workflow_dashboard as page
page.RUNS=OUT/'chain_case'
def no_launch(*a,**kw):raise RuntimeError('Read-only UI inventory prohibits process launches')
page.subprocess.Popen=no_launch
app=AppTest.from_string('from src.web.creative_workflow_dashboard import page_creative_workflow\npage_creative_workflow()',default_timeout=15).run()
app.session_state['creative_run_dir']=str(OUT/'chain_case'/'run');app.run()
assert not app.exception
labels={kind:[item.label for item in getattr(app,kind)] for kind in ['button','selectbox','checkbox','text_input','text_area','expander']}
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
receipt=read(OUT/'chain_case'/'run'/'writer_script.json')
code_values=[str(item.value) for item in app.code]
from src.content_factory.creative_stage_debug import CreativeStageCommandService
snapshot=CreativeStageCommandService(OUT/'chain_case'/'run').inspect()
from scripts.debug_creative_workflow import parser as debug_parser
from scripts.run_creative_workflow import parser as run_parser
commands=[]
for action in debug_parser()._actions:
 if isinstance(action.choices,dict):commands.extend(action.choices)
options=[opt for action in run_parser()._actions for opt in action.option_strings]
model_input=receipt['request']['messages'][-1]['content'];system_prompt=receipt['request']['messages'][0]['content']
result={'schema':'p1_input_preview_surface_inventory/v1','direction_requirement':'P1 文本阶段调试：冻结输入预览','ui_labels':labels,'ui_exception_count':len(app.exception),'current_model_input_displayed_in_code_view':any(model_input in value for value in code_values),'current_model_prompt_displayed_in_code_view':any(system_prompt in value for value in code_values),'cli_commands':commands,'runner_debug_options':[option for option in options if any(word in option for word in ['stage','preview','dry-run','freeze'])],'inspect_current_stage_keys':list(snapshot['stages'][-1]),'stage_receipt_has_request_messages':bool(receipt['request']['messages']),'command_service_public_methods':[n.name for n in ast.walk(ast.parse((ROOT/'src/content_factory/creative_stage_debug.py').read_text(encoding='utf-8'))) if isinstance(n,ast.ClassDef) and n.name=='CreativeStageCommandService' for n in n.body if isinstance(n,ast.FunctionDef) and not n.name.startswith('_')],'finding':'Request messages are persisted, but the shared command service and debug UI have no frozen input/full prompt preview entry. Existing inspect exposes hashes and artifact paths; no preview command or before-call preview control is wired.','model_calls_started':0,'media_review_performed':False}
(OUT/'input_preview_inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:result[k] for k in ['ui_exception_count','current_model_input_displayed_in_code_view','current_model_prompt_displayed_in_code_view','cli_commands','runner_debug_options','command_service_public_methods','stage_receipt_has_request_messages']},ensure_ascii=False))
