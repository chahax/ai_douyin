"""Passive visible selection evidence; never proof that all statuses are shown."""

LIST_FILTER_INVENTORY_JS = r"""() => {
 const visible=e=>!!e&&e.isConnected&&!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const clean=v=>String(v||'').replace(/https?:\/\/[^\s<>"']+/gi,'[link omitted]')
  .replace(/\b(token|session|cookie|secret|authorization|password)\s*[:=]\s*[^\s,;]+/gi,'$1=[redacted]')
  .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi,'[email omitted]').slice(0,200);
 const selector='.arco-select,[role="combobox"],[role="radio"],[role="tab"],[aria-selected],input[type="radio"]';
 const nodes=Array.from(document.querySelectorAll(selector)).filter(visible);
 const fieldLabel=e=>{const label=e.closest('.arco-form-item')?.querySelector('.arco-form-item-label');return visible(label)?clean(label.innerText||''):'';};
 return {schema:'fanqie_visible_list_filters/v1',controls:nodes.slice(0,60).map(e=>({
  tag:e.tagName.toLowerCase(),role:clean(e.getAttribute('role')),
  label:clean(e.getAttribute('aria-label')),visible_text:clean(e.innerText||''),
  aria_selected:e.getAttribute('aria-selected'),aria_checked:e.getAttribute('aria-checked'),
  checked:e.matches('input[type="radio"]')?e.checked:null,
  disabled:!!e.disabled||e.getAttribute('aria-disabled')==='true',
  selected_class:e.classList.contains('arco-radio-checked')||e.classList.contains('arco-tabs-header-title-active'),
  field_label:fieldLabel(e)
 })),visible_control_count:nodes.length,truncated:nodes.length>60,
 input_values_read:false,filter_changed:false,request_query_read:false,
 all_statuses_included:null,completeness:'unknown',
 limitations:['Visible controls only; defaults and server-side filters are not inferred.']};
}"""
