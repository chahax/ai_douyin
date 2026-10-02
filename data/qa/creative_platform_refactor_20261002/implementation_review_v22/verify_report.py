from pathlib import Path
import json,hashlib,ast
from playwright.sync_api import sync_playwright
ROOT=Path.cwd();OUT=ROOT/'data/qa/creative_platform_refactor_20261002/implementation_review_v22'
report=json.loads((OUT/'review_report.json').read_text(encoding='utf-8'))
missing=[]
for item in report['roadmap']:
 for ref in item['sources']:
  p=ROOT/ref['path']
  if not p.is_file():missing.append(ref)
  elif ref.get('line') and len(p.read_text(encoding='utf-8-sig').splitlines())<ref['line']:missing.append(ref)
assert not missing,missing
for name in ('build_report.py','inventory_and_probe.py','test_inflight_feedback_contract.py'):ast.parse((OUT/name).read_text(encoding='utf-8-sig'))
check={'source_references_valid':True,'qa_script_syntax_valid':True,'renders':[]}
with sync_playwright() as p:
 browser=p.chromium.launch(channel='msedge',headless=True)
 for label,width,height in [('desktop',1365,960),('mobile',430,932)]:
  page=browser.new_page(viewport={'width':width,'height':height},device_scale_factor=1)
  page.route('http://**/*',lambda r:r.abort());page.route('https://**/*',lambda r:r.abort())
  page.goto((OUT/'review_report.html').as_uri());page.wait_for_load_state('load')
  page.screenshot(path=str(OUT/('report_'+label+'.png')))
  measured=page.evaluate('({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,articles:document.querySelectorAll("article").length,links:document.querySelectorAll("a").length})')
  assert measured['width']>=measured['scrollWidth'],measured
  check['renders'].append({'layout':label,**measured})
  page.close()
 browser.close()
check['reviewed_source_unchanged']=all(hashlib.sha256((ROOT/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in report['code_inventory'])
assert check['reviewed_source_unchanged']
(OUT/'report_validation.json').write_text(json.dumps(check,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(check,ensure_ascii=False))
