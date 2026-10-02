from pathlib import Path
import json
from html.parser import HTMLParser
from urllib.parse import urlparse,unquote
OUT=Path(__file__).resolve().parent
class Links(HTMLParser):
 def __init__(self):super().__init__();self.links=[]
 def handle_starttag(self,tag,attrs):
  if tag=='a':self.links.extend(value for key,value in attrs if key=='href')
parser=Links();parser.feed((OUT/'confirmation_report.html').read_text(encoding='utf-8'))
missing=[]
for href in parser.links:
 u=urlparse(href)
 p=Path(unquote(u.path).lstrip('/')) if u.scheme=='file' else OUT/unquote(u.path)
 if not p.is_file():missing.append(str(p))
assert not missing,missing
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
 browser=pw.chromium.launch(channel='msedge',headless=True)
 page=browser.new_page(viewport={'width':1280,'height':1000})
 page.goto((OUT/'confirmation_report.html').as_uri(),wait_until='load')
 assert page.title()=='v19 与返修恢复独立复核'
 assert '尚不能确认整体完成' in page.inner_text('body')
 assert '291' in page.inner_text('table')
 page.screenshot(path=str(OUT/'confirmation_report.png'),full_page=True)
 page.set_viewport_size({'width':390,'height':844})
 page.reload(wait_until='load')
 overflow=page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
 browser.close()
assert not overflow
result={'local_links_checked':len(parser.links),'missing_links':missing,'desktop_rendered':True,'mobile_page_overflow':overflow,'report':'confirmation_report.html','screenshot':'confirmation_report.png'}
(OUT/'artifact_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
