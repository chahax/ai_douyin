"""Checkpoint every readable chapter; never treat a partial corpus as a full book."""
import hashlib
import json
import os
import re
import time
from pathlib import Path
from .fanqie_book_inspect import BookInspectionStopped

ITEMS = '''Array.from(document.querySelectorAll('.catalogue__item-ImEeJx,[class*="catalogue__item"]:not([class*="text"]):not([class*="header"]):not([class*="list"])')).filter(e=>e.querySelector('[class*="catalogue__item-text"]'))'''
CATALOG = '() => '+ITEMS+'''.map(e=>({title:e.querySelector('[class*="catalogue__item-text"]').innerText.trim(),locked:!!e.querySelector('svg.catalogue__item-icon-VgbkwJ,[class*="lock"]')}))'''
READER = '''() => {const u=new URL(location.href),e=document.querySelector('#content,[class*="chapter-content"]');return {url:u.href,book_id:u.searchParams.get('book_id'),item_id:u.searchParams.get('item_id'),text:e?e.innerText.trim():''}}'''

def atomic(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,path)

def valid_reader(reader, book_id, previous=None):
    return (reader.get('book_id')==book_id and bool(re.fullmatch(r'[0-9]{10,24}',reader.get('item_id') or ''))
        and len(reader.get('text',''))>=100
        and not any(x in reader['text'] for x in ('试读结束','付费章节','请先登录','开通会员'))
        and (not previous or (reader['item_id']!=previous['item_id'] and reader['text']!=previous['text'])))

def collect_corpus(page, inspection, guard, checkpoint, root, *, limit=0, resource_id, command_id):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    book=inspection['book_id'];title=inspection['book_name']
    existing=root/'MANIFEST.json'
    if existing.exists():
        prior_manifest=json.loads(existing.read_text(encoding='utf-8'))
        if (prior_manifest.get('book_id'),prior_manifest.get('book_name'),prior_manifest.get('resource_id'))!=(book,title,resource_id):
            raise BookInspectionStopped('corpus_identity_changed')
        history=root/'history'/f"{prior_manifest['command_id']}.json"
        if not history.exists():atomic(history,prior_manifest)
    manifest={'schema':'fanqie_readable_corpus/v1','book_id':book,'book_name':title,'resource_id':resource_id,
        'command_id':command_id,'chapters':[],'skipped':[],'status':'collecting',
        'full_book_confirmed':False,'requested_limit':limit,'promotion_task_active':False}
    def save():
        manifest['updated_at']=time.time()
        manifest['characters']=sum(c['characters'] for c in manifest['chapters'])
        atomic(root/'MANIFEST.json',manifest)
        checkpoint({**inspection,'corpus':manifest,'corpus_path':str(root/'MANIFEST.json')})
    def evaluate(js):
        guard();return page.evaluate(js)
    try:
        prior=None;stable=0;catalog=[]
        for _ in range(30):
            catalog=evaluate(CATALOG)
            if not catalog:raise BookInspectionStopped('corpus_catalogue_missing')
            stable=stable+1 if catalog==prior else 0
            if stable>=3:break
            prior=catalog
            evaluate('''() => {for(const e of document.querySelectorAll('[class*="catalogue"],.muye-reader-content-16,.muye-reader-box')){if(e.scrollHeight>e.clientHeight)e.scrollTop=e.scrollHeight;}window.scrollTo(0,document.body.scrollHeight)}''')
            page.wait_for_timeout(500)
        if stable<3:raise BookInspectionStopped('catalogue_not_stable')
        titles=[c['title'] for c in catalog]
        if len(titles)!=len(set(titles)):raise BookInspectionStopped('catalogue_titles_ambiguous')
        manifest['catalogue']=catalog
        manifest['catalogue_count']=len(catalog)
        manifest['catalogue_evidence']='DOM complete stable scan; no publisher total asserted'
        save()
        previous=inspection.get('chapter')
        for index,entry in enumerate(catalog[:limit or len(catalog)],1):
            guard()
            if entry['locked']:
                manifest['skipped'].append({'index':index,**entry,'reason':'chapter_locked'});save();continue
            cached=root/'chapters'/f'{index:05d}.json'
            if cached.exists():
                c=json.loads(cached.read_text(encoding='utf-8'))
                if (c['book_id']!=book or c['title']!=entry['title'] or
                    hashlib.sha256(c['text'].encode()).hexdigest()!=c['sha256'] or not valid_reader(c,book)):
                    raise BookInspectionStopped('cached_source_mismatch')
            else:
                target=json.dumps(entry['title'],ensure_ascii=False)
                selection=evaluate('() => {const items='+ITEMS+''';const matches=items.filter(e=>e.querySelector('[class*="catalogue__item-text"]').innerText.trim()==='''+target+''');if(matches.length!==1)return false;const e=matches[0];if(e.querySelector('svg.catalogue__item-icon-VgbkwJ,[class*="lock"]'))return false;e.click();return true;}''')
                if not selection:raise BookInspectionStopped('chapter_selection_changed')
                c={}
                for _ in range(20):
                    page.wait_for_timeout(400);c=evaluate(READER)
                    if valid_reader(c,book,previous if index>1 else None):break
                if not valid_reader(c,book,previous if index>1 else None):raise BookInspectionStopped('chapter_body_unavailable_or_stale')
                c.update(title=entry['title'],index=index,sha256=hashlib.sha256(c['text'].encode()).hexdigest(),
                    command_id=command_id,observed_at=time.time())
                atomic(cached,c)
                previous=c
            if c['item_id'] in {x['item_id'] for x in manifest['chapters']}:
                raise BookInspectionStopped('duplicate_chapter_id')
            manifest['chapters'].append({k:c[k] for k in ('index','title','item_id','sha256','url')} | {'path':str(cached.resolve()),'characters':len(c['text'])})
            save()
        manifest['status']='accessible_catalogue_complete' if not limit or limit>=len(catalog) else 'explicit_limit_reached'
        save()
        return {**inspection,'corpus':manifest,'corpus_path':str(root/'MANIFEST.json')}
    except Exception as exc:
        manifest.update(status='stopped',stop_reason=str(exc) if isinstance(exc,BookInspectionStopped) else type(exc).__name__)
        save();raise
