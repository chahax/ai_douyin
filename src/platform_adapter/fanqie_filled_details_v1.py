"""Read a filled alias's existing links on a caller-owned Fanqie Page.

This adapter opens only the exact, already visible filled-details control.
It never uploads, submits, changes an alias or settles an old receipt. The
caller owns the managed account/identity guard and immutable checkpoints.
"""
import json
import re
from urllib.parse import urlsplit


class DetailsNotConfirmed(ValueError):
    pass


def _need(value, reason):
    if not value:
        raise DetailsNotConfirmed(reason)


def _target(book_id, book_name, alias):
    _need(isinstance(book_id, str) and re.fullmatch(r"\d{10,24}", book_id), "exact_book_id_required")
    for value in (book_name, alias):
        _need(isinstance(value, str) and value == value.strip() and 0 < len(value) <= 200
              and not any(ord(c) < 32 for c in value), "exact_target_required")
    return dict(book_id=book_id, book_name=book_name, alias=alias)


ROW_JS = r"""() => {
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&
  getComputedStyle(e).display!=='none'&&getComputedStyle(e).visibility!=='hidden'&&
  !e.closest('[hidden],[aria-hidden="true"]');
 const text=e=>(e?.innerText||'').trim().replace(/\s+/g,' ');
 const tables=Array.from(document.querySelectorAll('table')).filter(visible);
 const headers=tables.length===1?Array.from(tables[0].querySelectorAll('thead th')).map(text):[];
 const all=Array.from(document.querySelectorAll('tbody tr'));
 const rows=all.map((row,index)=>({index,visible:visible(row),
  cells:Array.from(row.querySelectorAll('td')).map(text),
  book_names:Array.from(row.querySelectorAll('[class*="book-name"]')).filter(visible).map(text)})).filter(r=>r.visible);
 return {schema:'fanqie_filled_details_rows/v1',location:{origin:location.origin,path:location.pathname},
  visible_tables:tables.length,headers,total_rows:all.length,rows:rows.slice(0,200),truncated:rows.length>200,
  loading:Array.from(document.querySelectorAll('.arco-spin-loading,.arco-spin-loading-layer,[aria-busy="true"]')).some(visible)};
}"""


PANEL_JS = r"""() => {
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&
  getComputedStyle(e).display!=='none'&&getComputedStyle(e).visibility!=='hidden'&&
  !e.closest('[hidden],[aria-hidden="true"]');
 const text=e=>(e?.innerText||'').trim().replace(/\s+/g,' ');
 const candidates=Array.from(document.querySelectorAll('[role="dialog"],.arco-modal,.arco-drawer-content')).filter(visible);
 const roots=candidates.filter(e=>!candidates.some(other=>other!==e&&other.contains(e)));
 const root=roots.length===1?roots[0]:null;
 const raw=root?text(root):'';
 const controls=root?Array.from(root.querySelectorAll('button,a,input,select,textarea,[role="button"],[role="link"]')).filter(visible):[];
 const links=root?Array.from(root.querySelectorAll('a[href]')).filter(visible).map(e=>{
  try{const u=new URL(e.getAttribute('href'),location.href);
   return u.protocol==='https:'&&['www.douyin.com','douyin.com','v.douyin.com'].includes(u.hostname)
    ?{text:text(e).slice(0,300),origin:u.origin,path:u.pathname}:null}catch{return null}}).filter(Boolean):[];
 return {schema:'fanqie_filled_details_panel/v1',location:{origin:location.origin,path:location.pathname},
  visible_panels:roots.length,panel_observed:!!root,text:raw.slice(0,16000),
  controls:controls.slice(0,80).map(e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role')||'',
   text:text(e).slice(0,500),type:e.getAttribute('type')||'',placeholder:e.getAttribute('placeholder')||'',
   disabled:e.matches(':disabled,[aria-disabled="true"]')})),links:links.slice(0,100),
  truncated:raw.length>16000||controls.length>80||links.length>100,input_values_read:false,
  submission_performed:false,append_capability_verified:false};
}"""


def _row(observation, target):
    _need(observation.get('schema') == 'fanqie_filled_details_rows/v1'
          and observation.get('location') == {'origin': 'https://kol.fanqieopen.com', 'path': '/page/promotion-list'}
          and observation.get('visible_tables') == 1 and observation.get('truncated') is False
          and observation.get('loading') is False, 'promotion_table_not_ready')
    headers = observation['headers']
    names = ('关键词', '书本信息', '发文详情')
    _need(all(headers.count(name) == 1 for name in names), 'promotion_headers_not_unique')
    columns = {name: headers.index(name) for name in names}
    matches = []
    for row in observation['rows']:
        cells = row['cells']
        if len(cells) != len(headers) or cells[columns['关键词']] != target['alias']:
            continue
        book = cells[columns['书本信息']]
        ids = re.findall(r'ID\s*[:：]?\s*(\d{10,24})(?!\d)', book, re.I)
        if ids != [target['book_id']] or target['book_name'] not in row['book_names']:
            continue
        label = cells[columns['发文详情']]
        match = re.fullmatch(r'已填写\s*[（(]\s*(\d+)\s*条\s*[）)]', label)
        _need(match is not None and int(match.group(1)) > 0, 'filled_details_control_not_confirmed')
        matches.append(dict(index=row['index'], label=label, count=int(match.group(1)), cells=cells))
    _need(len(matches) == 1, 'exact_filled_alias_row_not_unique')
    return matches[0]


def inspect_filled_details(page, *, book_id, book_name, alias, guard, checkpoint):
    """One native details click, followed solely by bounded DOM observations."""
    target = _target(book_id, book_name, alias)
    guard()
    current = page._cmd('current_url')['url']
    parsed = urlsplit(current)
    _need(parsed.scheme == 'https' and parsed.netloc == 'kol.fanqieopen.com'
          and parsed.path == '/page/promotion-list', 'original_promotion_page_required')
    panel_before = page.evaluate(PANEL_JS)
    checkpoint('panel_before', dict(target=target, observation=panel_before))
    _need(panel_before.get('location') == {'origin': 'https://kol.fanqieopen.com', 'path': '/page/promotion-list'}
          and panel_before.get('visible_panels') == 0 and panel_before.get('panel_observed') is False,
          'preexisting_details_panel_requires_review')
    samples, previous, stable = [], None, 0
    for _ in range(16):
        guard()
        before = page.evaluate(ROW_JS)
        samples.append(before)
        signature = json.dumps(before, ensure_ascii=False, sort_keys=True)
        stable = stable + 1 if signature == previous else 1
        previous = signature
        if (stable >= 2 and before.get('visible_tables') == 1 and before.get('headers')
                and before.get('loading') is False and before.get('truncated') is False):
            break
        page.wait_for_timeout(250)
    checkpoint('table', dict(target=target, samples=samples))
    selected = _row(before, target)
    checkpoint('row', dict(target=target, observation=before, selected=selected))
    selector = (':nth-match(tbody tr, '+str(selected['index']+1)+') >> xpath=.//*[normalize-space(.)='
                +json.dumps(selected['label'], ensure_ascii=False)+' and not(*[normalize-space(.)='
                +json.dumps(selected['label'], ensure_ascii=False)+'])]')
    control = page.locator(selector)
    _need(control.count() == 1, 'filled_details_trigger_not_unique')
    trigger = control.evaluate("""el=>({text:(el.innerText||'').trim().replace(/\\s+/g,' '),
        visible:el.isConnected&&el.getClientRects().length>0&&getComputedStyle(el).visibility!=='hidden',
        disabled:el.matches(':disabled,[aria-disabled="true"]')})""")
    _need(trigger.get('text') == selected['label'] and trigger.get('visible') is True
          and trigger.get('disabled') is False, 'filled_details_trigger_changed')
    guard()
    _need(_row(page.evaluate(ROW_JS), target) == selected, 'filled_alias_changed_before_details')
    checkpoint('click_intent', dict(target=target, selected=selected, trigger=trigger, details_click_limit=1))
    control.click(timeout=8000)
    observations = []
    for _ in range(20):
        guard()
        observed = page.evaluate(PANEL_JS)
        _need(observed.get('location', {}).get('origin') == 'https://kol.fanqieopen.com', 'details_origin_changed')
        observations.append(observed)
        if observed.get('panel_observed') is True:
            break
        page.wait_for_timeout(250)
    checkpoint('panel', dict(target=target, observations=observations))
    _need(observations[-1].get('panel_observed') is True and observations[-1].get('truncated') is False,
          'filled_details_panel_not_confirmed')
    return dict(schema='fanqie_filled_details_observation/v1', target=target, previous_count=selected['count'],
                panel=observations[-1], details_clicks=1, uploaded=False, submitted=False,
                panel_transition='none_to_one_after_bound_details_click',
                append_capability_verified=False, old_ledger_changed=False)
