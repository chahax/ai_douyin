"""Passive discovery on the caller-owned promotion list; no inferred selector."""

DISCOVER_JS = r"""() => {
 const locationEvidence={origin:location.origin,path:location.pathname};
 if(locationEvidence.origin!=='https://kol.fanqieopen.com'||locationEvidence.path!=='/page/promotion-list')
  return {schema:'fanqie_lookup_controls/v1',location:locationEvidence,accepted:false,reason:'origin_path_mismatch',metadata_only:true,search_performed:false};
 const visible=e=>!!e&&e.isConnected&&!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const clean=v=>String(v||'').replace(/https?:\/\/[^\s<>"']+/gi,'[link omitted]')
  .replace(/\b(token|session|cookie|secret|authorization|password)\s*[:=]\s*[^\s,;]+/gi,'$1=[redacted]').slice(0,160);
 const meta=e=>({tag:e.tagName.toLowerCase(),role:clean(e.getAttribute('role')),id:clean(e.id),
  class_tokens:Array.from(e.classList).slice(0,12).map(clean),aria_label:clean(e.getAttribute('aria-label')),
  visible_text:e.matches('input')?null:clean(e.innerText||''),disabled:!!e.disabled||e.getAttribute('aria-disabled')==='true'});
 const tabs=Array.from(document.querySelectorAll('[role="tab"]')).filter(visible);
 const combos=Array.from(document.querySelectorAll('[role="combobox"],.arco-select')).filter(visible);
 const inputs=Array.from(document.querySelectorAll('input')).filter(e=>visible(e)&&['text','search'].includes(e.type));
 const tables=Array.from(document.querySelectorAll('table')).filter(visible);
 const table=tables.length===1?tables[0]:null;
 const heads=table?Array.from(table.querySelectorAll('thead')).filter(visible):[];
 const headers=heads.length===1?Array.from(heads[0].querySelectorAll('th')).filter(visible).map(e=>clean(e.innerText||'')):[];
 const loading=Array.from(document.querySelectorAll('.arco-spin-loading,.arco-spin-loading-layer,[aria-busy="true"]')).some(visible);
 return {schema:'fanqie_lookup_controls/v1',location:locationEvidence,accepted:true,
  tabs:tabs.slice(0,20).map(e=>({...meta(e),aria_selected:e.getAttribute('aria-selected')})),
  comboboxes:combos.slice(0,20).map(meta),
  text_inputs:inputs.slice(0,20).map(e=>({...meta(e),type:e.type,placeholder:clean(e.getAttribute('placeholder')),read_only:!!e.readOnly})),
  visible_tables_count:tables.length,table:table?{headers,loading,
   empty_state:Array.from(document.querySelectorAll('.arco-empty,.arco-table-empty')).some(visible),
   ready:heads.length===1&&headers.length>0&&!loading}:null,
  truncated:tabs.length>20||combos.length>20||inputs.length>20,
  input_values_read:false,metadata_only:true,search_performed:false,selector_confirmed:false};
}"""


def discover(page):
    result = page.evaluate(DISCOVER_JS)
    if not isinstance(result, dict) or result.get('schema') != 'fanqie_lookup_controls/v1':
        raise ValueError('lookup_controls_observation_invalid')
    if result.get('accepted') is not True:
        raise ValueError('lookup_controls_origin_path_mismatch')
    return result
