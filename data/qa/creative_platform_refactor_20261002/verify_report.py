from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
from datetime import datetime, timezone
import hashlib, json

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
REPORT = OUT / 'direction_report.html'
BASE = ROOT / 'data/qa/architecture_audit_20261001'
RECHECKED = [
 'AGENTS.md', 'scripts/run_creative_workflow.py',
 'src/content_factory/creative_workflow.py',
 'src/content_factory/creative_segmented_director.py',
 'src/content_factory/creative_full_script_revision.py',
 'src/content_factory/creative_seedance_segments.py',
 'scripts/run_creative_seedance_segment.py',
 'scripts/run_manual_review_deferred_segment.py',
 'src/web/creative_workflow_dashboard.py',
 'src/content_factory/creative_evaluation.py',
 'src/content_factory/creative_governed_runtime.py',
 'docs/REUSABLE_VIDEO_WORKFLOW.md', 'docs/SCRIPT_VIDEO_RUN.md',
 'README.md', 'docs/SYSTEM_ARCHITECTURE.md',
]
ADDITIONAL = [
 'config/creative_workflow_budget_v5.json',
 'data/creative_governance/20261001_v17_history_usage/dataset_manifest.json',
 'data/creative_governance/20261001_v17_history_usage/labels.json',
 'src/content_factory/creative_workflow_roles.py',
 'src/content_factory/creative_narrative_transfer.py',
 'src/content_factory/script_video_review.py',
 'scripts/run_script_video.py',
]

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
old={row['path']:row for row in json.loads((BASE/'inventory.json').read_text(encoding='utf-8'))}
files=[]
for name in RECHECKED+ADDITIONAL:
 p=ROOT/name
 row={'path':name,'sha256':sha(p),'lines':len(p.read_bytes().splitlines()),'size_bytes':p.stat().st_size}
 if name in RECHECKED:
  row['matches_prior_graphify_snapshot']=row['sha256']==old.get(name,{}).get('sha256')
  if not row['matches_prior_graphify_snapshot']: raise RuntimeError('Prior snapshot changed: '+name)
 files.append(row)
cases=json.loads((ROOT/ADDITIONAL[1]).read_text(encoding='utf-8'))['cases']
labels=json.loads((ROOT/ADDITIONAL[2]).read_text(encoding='utf-8'))['labels']
audit=json.loads((BASE/'audit_manifest.json').read_text(encoding='utf-8'))
manifest={
 'schema':'creative_platform_refactor_direction/v1',
 'created_at':datetime.now(timezone.utc).isoformat(),
 'product_direction':'AI screenplay and video production platform',
 'user_confirmed_debug_scope':['text_stages','video_segments'],
 'status':'proposal_only',
 'snapshot_rechecked_count':len(RECHECKED),
 'all_rechecked_match_prior_snapshot':True,
 'prior_graphify_audit':{'manifest':'../architecture_audit_20261001/audit_manifest.json','graphify_version':audit['graphify_version'],'git_head':audit['git_head'],'new_graph_extraction_performed':False,'tests_not_repeated':audit['tests']},
 'current_dataset':{'case_count':len(cases),'approved_cases':sum(c.get('label_status')=='approved' for c in cases),'approved_labels':sum(c.get('label_status')=='approved' for c in labels),'candidate_case_count':sum(c.get('label_status')=='candidate' for c in cases)},
 'current_budget':json.loads((ROOT/ADDITIONAL[0]).read_text(encoding='utf-8')),
 'source_files':files,
 'external_sources':[{'url':'https://www.iso.org/standard/74393.html','purpose':'Architecture description scope, official abstract only'},{'url':'https://www.anthropic.com/engineering/building-effective-agents','purpose':'Workflow and intermediate checks, vendor engineering practice'},{'url':'https://airc.nist.gov/airmf-resources/playbook/measure/','purpose':'Evaluation methods and measurement limitations'}],
 'work_performed':{'business_code_modified':False,'existing_documents_modified':False,'historical_task_records_modified':False,'paid_calls_started':0,'media_generated':False,'video_or_audio_content_inspected':False,'production_publishing_performed':False},
 'report':{'path':REPORT.name,'sha256':sha(REPORT)},
}
(OUT/'evidence_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

class Check(HTMLParser):
 def __init__(self):super().__init__();self.ids=[];self.links=[];self.headings=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if 'id' in a:self.ids.append(a['id'])
  if tag=='a' and 'href' in a:self.links.append(a['href'])
  if tag=='h2':self.headings.append(tag)
check=Check();check.feed(REPORT.read_text(encoding='utf-8-sig'))
missing=[]
for href in check.links:
 parts=urlsplit(href)
 if parts.scheme or parts.netloc:continue
 if not parts.path:
  if parts.fragment and parts.fragment not in check.ids:missing.append(href)
 elif not (OUT/unquote(parts.path)).resolve().exists():missing.append(href)
if len(check.ids)!=len(set(check.ids)):raise RuntimeError('Duplicate element IDs')
if missing:raise RuntimeError('Missing links: '+repr(missing))
result={'schema':'creative_refactor_report_verification/v1','html_sections':len(check.headings),'local_links_checked':sum(not urlsplit(h).scheme for h in check.links),'missing_links':missing,'source_snapshot_count':len(RECHECKED),'source_files_changed':[],'browser':None}
try:
 from playwright.sync_api import sync_playwright
 with sync_playwright() as pw:
  browser=None;launch_errors=[]
  for channel in ['msedge','chrome',None]:
   try:
    kw={'headless':True}
    if channel:kw['channel']=channel
    browser=pw.chromium.launch(**kw);break
   except Exception as exc:launch_errors.append(type(exc).__name__+': '+str(exc).splitlines()[0])
  if browser is None:raise RuntimeError('No local Chromium browser: '+str(launch_errors))
  context=browser.new_context(viewport={'width':1360,'height':960},device_scale_factor=1)
  context.route('**/*',lambda route:route.abort() if route.request.url.startswith(('http:','https:')) else route.continue_())
  page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(REPORT.as_uri(),wait_until='load')
  assert page.title()=='AI 剧本与视频制作平台重构方向报告'
  assert page.locator('#mode-result').inner_text().startswith('调试模式')
  page.get_by_role('button',name='自动推进模式').click()
  assert page.locator('#mode-result').inner_text().startswith('自动推进模式')
  page.get_by_role('button',name='调试模式').click()
  for key in ['script','compiler','segment']:
   page.locator('#change-select').select_option(key)
   assert page.locator('#impact-list .impact-row').count()==4
   assert page.locator('#impact-note').inner_text()
  page.locator('#change-select').select_option('script')
  desktop_overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth')
  page.locator('header').screenshot(path=str(OUT/'report_header.png'))
  page.locator('#debug').screenshot(path=str(OUT/'report_debug.png'))
  page.locator('#impact').screenshot(path=str(OUT/'report_impact.png'))
  page.set_viewport_size({'width':390,'height':844})
  mobile_overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth')
  page.locator('header').screenshot(path=str(OUT/'report_mobile.png'))
  assert not desktop_overflow,'Desktop page overflow'
  assert not mobile_overflow,'Mobile page overflow'
  assert not errors,errors
  result['browser']={'rendered':True,'javascript_errors':errors,'mode_checks':2,'dependency_scenarios_checked':3,'desktop_horizontal_overflow':desktop_overflow,'mobile_horizontal_overflow':mobile_overflow,'screenshots':['report_header.png','report_debug.png','report_impact.png','report_mobile.png']}
  browser.close()
except Exception as exc:
 result['browser']={'rendered':False,'error':type(exc).__name__+': '+str(exc)}
for row in files:
 if sha(ROOT/row['path'])!=row['sha256']:result['source_files_changed'].append(row['path'])
(OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
if result['source_files_changed']:raise RuntimeError('Source changed during verification')
if not result['browser'].get('rendered'):raise RuntimeError('Browser verification failed')
