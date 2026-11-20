"""Exact read-only BookID lookup after pinned public-control discovery.

No promotion submission, native-response replay/reload, alias change or claim
settlement. DOM rows are evidence of this current view, never a v2 native task.
"""
import hashlib
import json
from pathlib import Path
import re

from .fanqie_lookup_controls_v1 import discover
from .fanqie_promotion_preflight_v1 import validate_target

ROOT=Path(__file__).resolve().parents[2]
VERSION='fanqie_promotion_lookup/v1'
SCOPE=('resource_id','binding_version','platform_identity_key','environment_key')
INPUT_KEYS=('tag','type','id','placeholder','aria_label','disabled','read_only')

TABLE_JS=r"""() => {
 if(location.origin!=='https://kol.fanqieopen.com'||location.pathname!=='/page/promotion-list')throw Error('lookup wrong page');
 const visible=e=>!!e&&e.isConnected&&!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const text=e=>(e?.innerText||'').trim().slice(0,500);
 const tables=Array.from(document.querySelectorAll('table')).filter(visible),table=tables.length===1?tables[0]:null;
 const heads=table?Array.from(table.querySelectorAll('thead')).filter(visible):[];
 const headers=heads.length===1?Array.from(heads[0].querySelectorAll('th')).filter(visible).map(text):[];
 const wrappers=Array.from(document.querySelectorAll('.arco-table')).filter(visible);
 const scope=table?.closest('.arco-table')||(wrappers.length===1?wrappers[0]:table);
 const loading=scope?[scope,...scope.querySelectorAll('.arco-spin-loading,.arco-spin-loading-layer,[aria-busy="true"]')]
  .some(e=>visible(e)&&(e.matches('.arco-spin-loading,.arco-spin-loading-layer')||e.getAttribute('aria-busy')==='true')):false;
 const rows=table?Array.from(table.querySelectorAll('tbody tr')).filter(visible):[];
 const emptyRows=rows.filter(row=>{const cells=Array.from(row.querySelectorAll('td')).filter(visible);
  return cells.length===1&&Number(cells[0].getAttribute('colspan'))===headers.length&&
   Array.from(cells[0].querySelectorAll('.arco-empty,.arco-table-empty')).some(visible);});
 const dataRows=rows.filter(row=>!emptyRows.includes(row));
 const next=Array.from(document.querySelectorAll('.arco-pagination-item-next,[aria-label="下一页"]')).filter(visible);
 const has_next=next.some(e=>!e.disabled&&e.getAttribute('aria-disabled')!=='true'&&!/disabled/.test(e.className));
 const empty=emptyRows.length>0||(scope?Array.from(scope.querySelectorAll('.arco-empty,.arco-table-empty')).some(visible):false);
 return {schema:'fanqie_lookup_DOM_table/v1',visible_tables_count:tables.length,headers,loading,
  ready:!!table&&heads.length===1&&headers.length>0&&!loading,
  rows:dataRows.slice(0,200).map(row=>({cells:Array.from(row.querySelectorAll('td')).filter(visible).map(text),
   book_name:Array.from(row.querySelectorAll('.book-name-iHil3A')).filter(visible).map(text)})),
  empty_placeholders:emptyRows.slice(0,4).map(row=>({text:text(row),colspan:Number(row.querySelector('td').getAttribute('colspan'))})),
  empty_state:empty,truncated:dataRows.length>200,has_next,pagination_ambiguous:next.length>1,
  input_values_read:false,native_identity_verified:false};
}"""


def validate_lookup_target(book_id,book_name,alias):
    validate_target(book_id,book_name)
    if not isinstance(alias,str) or not alias.strip() or alias!=alias.strip() or len(alias)>200 or any(ord(c)<32 for c in alias):
        raise ValueError('exact_lookup_alias_required')


def _read(binding):
    if not isinstance(binding,dict)or set(binding)!={'path','sha256'}:raise ValueError('lookup_SHA_binding_required')
    path=Path(binding['path']).resolve()
    if (not path.is_relative_to(ROOT)or path.stat().st_size>131072
            or hashlib.sha256(path.read_bytes()).hexdigest()!=binding['sha256']):
        raise ValueError('lookup_evidence_changed')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def validate_request(binding,subject,*,book_id,book_name,alias):
    request=_read(binding)
    expected={'schema','purpose',*SCOPE,'book_id','book_name','alias','source_controls','target_input','trigger'}
    if (set(request)!=expected or request['schema']!='fanqie_promotion_lookup_request/v1'
            or request['purpose']!='read_only_exact_book_alias_query' or request['trigger']!='Enter'
            or any(request[k]!=subject[k]for k in SCOPE)
            or any(request[k]!=v for k,v in [('book_id',book_id),('book_name',book_name),('alias',alias)])):
        raise ValueError('lookup_request_scope_changed')
    source=_read(request['source_controls'])
    if (source.get('schema')!='fanqie_promotion_lookup_step/v1' or source.get('stage')!='controls_ready'
            or any(source.get('subject',{}).get(k)!=subject[k]for k in SCOPE)):
        raise ValueError('lookup_control_evidence_scope_changed')
    observation=source.get('observation',{});target=request['target_input']
    if (observation.get('schema')!='fanqie_lookup_controls/v1' or observation.get('accepted')is not True
            or target not in observation.get('text_inputs',[]) or target.get('tag')!='input'
            or target.get('type')not in ('text','search') or target.get('disabled')is not False
            or target.get('read_only')is not False):
        raise ValueError('lookup_input_not_observed_editable')
    if len([c for c in observation.get('comboboxes',[])if c.get('visible_text')=='BookID'])!=1:
        raise ValueError('lookup_BookID_mode_not_observed')
    return request


def _same_input(left,right):return all(left.get(k)==right.get(k)for k in INPUT_KEYS)


def _selector(target):
    for key,attribute in [('id','id'),('placeholder','placeholder'),('aria_label','aria-label')]:
        if target.get(key):return 'input['+attribute+'='+json.dumps(target[key],ensure_ascii=False)+']:visible'
    return 'input:visible'


def _query_state_js(target,book_id):
    # Only this exact freshly observed public query input may have its value
    # compared, after our fill. No arbitrary input value is returned or read.
    wanted={k:target.get(k)for k in INPUT_KEYS}
    return r"""() => {const wanted="""+json.dumps(wanted,ensure_ascii=False)+',bookID='+json.dumps(book_id)+r""";
     if(location.origin!=='https://kol.fanqieopen.com'||location.pathname!=='/page/promotion-list')
      return {unique:false,value_matches:false,query_value_read:false};
     const visible=e=>e.isConnected&&!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
     const items=Array.from(document.querySelectorAll('input')).filter(e=>visible(e)&&
      e.type===wanted.type&&e.id===(wanted.id||'')&&(e.getAttribute('placeholder')||'')===(wanted.placeholder||'')&&
      (e.getAttribute('aria-label')||'')===(wanted.aria_label||''));
     return {unique:items.length===1,value_matches:items.length===1&&items[0].value===bookID,query_value_read:items.length===1};}"""


def _fingerprint(table):
    return hashlib.sha256(json.dumps({k:table.get(k)for k in ('headers','rows','empty_state')},
        ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _interpret(table,book_id,book_name,alias):
    required=('关键词','书本信息','发文类型','别名状态','书籍状态','发文详情')
    if any(table['headers'].count(k)!=1 for k in required):return dict(status='query_headers_unconfirmed',matches=[])
    columns={k:table['headers'].index(k)for k in required};matches=[];conflicts=[]
    if not table['rows']and not table.get('empty_state'):
        return dict(status='query_empty_state_unconfirmed',matches=[])
    for row in table['rows']:
        if len(row['cells'])!=len(table['headers']):return dict(status='query_row_shape_unconfirmed',matches=[])
        cells=row['cells'];book=cells[columns['书本信息']]
        ids=re.findall(r'ID\s*[:：]?\s*([0-9]{10,24})(?![0-9])',book,re.I)
        if ids!=[book_id]:return dict(status='query_scope_unconfirmed',matches=[])
        if cells[columns['关键词']]!=alias:continue
        names=row.get('book_name',[])
        if names!=[book_name]:conflicts.append(row);continue
        matches.append(dict(book_id=book_id,book_name=book_name,alias=alias,
            publish_type=cells[columns['发文类型']],alias_status=cells[columns['别名状态']],
            book_status=cells[columns['书籍状态']],fill_status=cells[columns['发文详情']],source='visible_DOM_only'))
    if conflicts or len(matches)>1:return dict(status='query_target_ambiguous',matches=matches,conflicts=conflicts)
    if table['truncated']or table['has_next']or table['pagination_ambiguous']:
        return dict(status='query_current_view_incomplete',matches=matches)
    return dict(status='target_observed'if matches else'not_observed_in_current_query',matches=matches)


def inspect_lookup(page,*,book_id,book_name,alias,subject,guard,checkpoint,lookup_request=None):
    validate_lookup_target(book_id,book_name,alias)
    result=dict(schema=VERSION,book_id=book_id,book_name=book_name,alias=alias,status='controls_discovered',
        searched=False,search_count=0,query_value_read=False,query_result_freshness_confirmed=False,
        native_identity_verified=False,publishable=False,platform_business_outcome='unknown',
        promotion_submitted=False,original_submission_claim_unchanged=True)
    if lookup_request is not None:result['lookup_request']=lookup_request
    def check():
        guard()
        if lookup_request is not None:validate_request(lookup_request,subject,book_id=book_id,book_name=book_name,alias=alias)
    def controls():check();value=discover(page);guard();return value
    def table():check();value=page.evaluate(TABLE_JS);guard();return value
    current=controls();checkpoint('controls_initial',current)
    for _ in range(12):
        if current.get('text_inputs')and current.get('comboboxes'):break
        check();page.wait_for_timeout(250);current=controls()
    checkpoint('controls_ready',current);result['controls']=current
    before=table();checkpoint('table_before',before)
    if lookup_request is None:return result
    request=validate_request(lookup_request,subject,book_id=book_id,book_name=book_name,alias=alias)
    target=request['target_input']
    if (len([c for c in current['comboboxes']if c.get('visible_text')=='BookID'])!=1
            or len([i for i in current['text_inputs']if _same_input(i,target)])!=1):
        result['status']='query_controls_or_table_unconfirmed';return result
    prior=None;before_stable=0
    for _ in range(20):
        fingerprint=_fingerprint(before)
        before_stable=before_stable+1 if before.get('ready')and fingerprint==prior else 1 if before.get('ready')else 0
        if before_stable>=2:break
        prior=fingerprint;check();page.wait_for_timeout(250);before=table()
    checkpoint('table_before_search',before)
    if before_stable<2:result['status']='query_table_baseline_unstable';return result
    rpc=getattr(page,'page',page);check();query=rpc.locator(_selector(target))
    if query.count()!=1:result['status']='query_input_not_unique';return result
    check();query.fill(book_id)
    check();confirmed=page.evaluate(_query_state_js(target,book_id));guard()
    checkpoint('query_confirmed',confirmed);result['query_value_read']=confirmed['query_value_read']
    if confirmed.get('unique')is not True or confirmed.get('value_matches')is not True:
        result['status']='query_input_value_unconfirmed';return result
    check();query.press('Enter');result.update(searched=True,search_count=1)
    checkpoint('query_entered',dict(key='Enter',count=1,query_kind='exact_public_book_id'))
    baseline=_fingerprint(before);saw_loading=False;stable=0;last=None;observations=[]
    for index in range(25):
        if index:check();page.wait_for_timeout(250)
        after=table();check();state=page.evaluate(_query_state_js(target,book_id));guard()
        mode=controls();result['query_value_read']=result['query_value_read']or state['query_value_read']
        query_confirmed=bool(state.get('value_matches')and state.get('unique')and
                len([c for c in mode['comboboxes']if c.get('visible_text')=='BookID'])==1)
        fingerprint=_fingerprint(after);saw_loading=saw_loading or after.get('loading')is True
        fresh=bool(query_confirmed and after.get('ready')and(saw_loading or fingerprint!=baseline))
        stable=stable+1 if fresh and fingerprint==last else 1 if fresh else 0;last=fingerprint
        observations.append(dict(index=index,ready=after.get('ready'),loading=after.get('loading'),
            fingerprint=fingerprint,changed_from_before=fingerprint!=baseline,
            query_confirmed=query_confirmed,stable_count=stable))
        if stable>=2:break
    checkpoint('query_observations',observations);checkpoint('table_after',after)
    result.update(query_result_freshness_confirmed=stable>=2,
        freshness_basis=('observed_loading_then_ready'if saw_loading else'visible_DOM_data_changed')if stable>=2 else None)
    if stable<2:
        result['status']='query_result_freshness_unconfirmed'if query_confirmed else'query_state_changed_during_wait'
        return result
    result.update(_interpret(after,book_id,book_name,alias))
    result['controls_after']=mode
    return result
