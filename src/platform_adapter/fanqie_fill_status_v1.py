"""Separate a visible fill status from its same-cell action control.

Only new DOM evidence is normalized. Historical rows without this optional
proof retain their original text and validation meaning.
"""
from copy import deepcopy
import re

SCHEMA = 'fanqie_fill_status_evidence/v1'
SCHEMA_V2 = 'fanqie_fill_status_evidence/v2'

# An expression embedded in the existing read-only managed table collector.
FILL_DETAIL_JS = r"""(cell) => {
 const norm=s=>String(s||'').trim().replace(/\s+/g,' ');
 const text=e=>norm(e?.innerText||e?.textContent||'');
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&
   getComputedStyle(e).visibility!=='hidden'&&getComputedStyle(e).display!=='none'&&
   !e.closest('[hidden],[aria-hidden="true"]');
 const selector='button,a,[role="button"],[role="link"]';
 const interactive=Array.from(cell.querySelectorAll(selector)).filter(e=>visible(e)&&!e.parentElement?.closest(selector));
 const ancestry=parent=>{
   const ancestors=[];let element=parent;
   while(element&&cell.contains(element)&&ancestors.length<5){
     const style=getComputedStyle(element);
     ancestors.push({tag:element.tagName.toLowerCase(),class_name:(element.getAttribute('class')||'').slice(0,256),
       role:(element.getAttribute('role')||'').slice(0,30),tabindex:(element.getAttribute('tabindex')||'').slice(0,20),
       cursor:style.cursor.slice(0,64),pointer_events:style.pointerEvents.slice(0,30),
       visible:visible(element),is_cell:element===cell});
     if(element===cell)break;element=element.parentElement;
   }return ancestors;
 };
 const publicPath=(node,action)=>{
   const xs=ancestry(node),classes=[action?'link':'','arco-table-cell-wrap-value','arco-table-cell','arco-table-td'];
   return xs.length===4&&xs.every((x,i)=>x.tag===['div','span','div','td'][i]&&x.class_name===classes[i]&&
     x.role===''&&x.tabindex===''&&x.visible&&x.pointer_events==='auto'&&x.cursor===(action&&i===0?'pointer':'auto')&&x.is_cell===(i===3));
 };
 const noninteractive=[];
 const walker=document.createTreeWalker(cell,NodeFilter.SHOW_TEXT);
 let node;while((node=walker.nextNode())){
   const parent=node.parentElement,value=norm(node.nodeValue);
   if(value&&visible(parent)&&!parent.closest(selector))noninteractive.push(node);
 }
 const statusNodes=noninteractive.filter(n=>norm(n.nodeValue)==='未填写'&&publicPath(n.parentElement,false));
 const roleless=Array.from(cell.querySelectorAll('div.link')).filter(e=>visible(e)&&text(e)==='回填发文'&&
   e.children.length===0&&Array.from(e.childNodes).filter(n=>n.nodeType===Node.TEXT_NODE&&norm(n.nodeValue)).length===1&&
   publicPath(e,true)&&statusNodes.length===1&&statusNodes[0].parentElement.parentElement===e.parentElement);
 const controls=[...interactive,...roleless].map(e=>({tag:e.tagName.toLowerCase(),
   role:e.getAttribute('role')||'',text:text(e),visible:true}));
 const statusTexts=noninteractive.filter(n=>!roleless.some(e=>e.contains(n))).map(n=>norm(n.nodeValue));
 const leaves=noninteractive.slice(0,16).map(n=>{const ancestors=ancestry(n.parentElement);
   return {text:norm(n.nodeValue).slice(0,256),ancestors,boundary_reached:ancestors.some(x=>x.is_cell)};});
 const rolelessProof=roleless.map((e,i)=>({schema:'fanqie_roleless_fill_action/v1',control_index:interactive.length+i,
   action_leaf:{text:'回填发文',ancestors:ancestry(e),boundary_reached:true},
   status_leaf:{text:'未填写',ancestors:ancestry(statusNodes[0].parentElement),boundary_reached:true},
   shared_status_parent:true,own_visible_text_node_count:1})).filter(x=>x.control_index<8);
 const raw=text(cell),truncated=raw.length>512||statusTexts.length>16||controls.length>8||
   statusTexts.some(x=>x.length>256)||controls.some(x=>x.text.length>256);
 const compact=s=>s.replace(/\s/g,'');
 const suffix=controls.map(x=>x.text).join('');
 const rawMatches=[statusTexts.join('')+suffix,suffix+statusTexts.join('')].some(s=>compact(s)===compact(raw));
 const ready=visible(cell)&&!truncated&&statusTexts.length===1&&statusTexts[0]==='未填写'&&
   controls.length<=1&&controls.every(x=>x.text==='回填发文')&&rawMatches;
 return {schema:'fanqie_fill_status_evidence/v2',raw_visible_text:raw.slice(0,512),
   status_source:'visible_non_action_text_nodes',status_texts:statusTexts.slice(0,16).map(x=>x.slice(0,256)),
   controls:controls.slice(0,8).map(x=>({...x,text:x.text.slice(0,256)})),
   roleless_action_evidence:rolelessProof,
   cell_visible:visible(cell),truncated,canonical_status:ready?'未填写':null,
   cell_structure:{schema:'fanqie_fill_cell_structure/v1',leaves,
     truncated:statusTexts.length>16||leaves.some(x=>!x.boundary_reached),
     public_dom_attributes_only:true,react_or_private_state_read:false}};
}"""


def _validate_structure(value):
    if (not isinstance(value, dict) or set(value) != {'schema', 'leaves', 'truncated',
            'public_dom_attributes_only', 'react_or_private_state_read'}
            or value['schema'] != 'fanqie_fill_cell_structure/v1'
            or value['public_dom_attributes_only'] is not True or value['react_or_private_state_read'] is not False
            or type(value['truncated']) is not bool or not isinstance(value['leaves'], list) or len(value['leaves']) > 16):
        raise ValueError('fill_status_structure_diagnostic_invalid')
    for leaf in value['leaves']:
        if (not isinstance(leaf, dict) or set(leaf) != {'text', 'ancestors', 'boundary_reached'}
                or not isinstance(leaf['text'], str) or len(leaf['text']) > 256
                or type(leaf['boundary_reached']) is not bool or not isinstance(leaf['ancestors'], list)
                or not 1 <= len(leaf['ancestors']) <= 5):
            raise ValueError('fill_status_structure_leaf_invalid')
        for ancestor in leaf['ancestors']:
            bounds = {'tag': 20, 'class_name': 256, 'role': 30, 'tabindex': 20, 'cursor': 64, 'pointer_events': 30}
            if (not isinstance(ancestor, dict) or set(ancestor) != {*bounds, 'visible', 'is_cell'}
                    or any(not isinstance(ancestor[key], str) or len(ancestor[key]) > limit for key, limit in bounds.items())
                    or type(ancestor['visible']) is not bool or type(ancestor['is_cell']) is not bool):
                raise ValueError('fill_status_structure_ancestor_invalid')


def _roleless_controls(records, controls):
    """Only the exact public Arco div.link structure observed in live readback."""
    if not isinstance(records, list) or len(records) > 8:
        raise ValueError('fill_status_roleless_proof_invalid')
    result = set()
    for record in records:
        if (not isinstance(record, dict) or set(record) != {'schema', 'control_index', 'action_leaf', 'status_leaf',
                'shared_status_parent', 'own_visible_text_node_count'}
                or record['schema'] != 'fanqie_roleless_fill_action/v1'
                or type(record['control_index']) is not int or not 0 <= record['control_index'] < len(controls)
                or record['control_index'] in result or record['shared_status_parent'] is not True
                or type(record['own_visible_text_node_count']) is not int or record['own_visible_text_node_count'] != 1):
            raise ValueError('fill_status_roleless_proof_invalid')
        action, status = record['action_leaf'], record['status_leaf']
        _validate_structure(dict(schema='fanqie_fill_cell_structure/v1', leaves=[action, status], truncated=False,
            public_dom_attributes_only=True, react_or_private_state_read=False))
        for leaf, first_class, first_cursor, expected_text in (
                (action, 'link', 'pointer', '回填发文'), (status, '', 'auto', '未填写')):
            path = leaf['ancestors']
            classes = [first_class, 'arco-table-cell-wrap-value', 'arco-table-cell', 'arco-table-td']
            if (leaf['text'] != expected_text or leaf['boundary_reached'] is not True or len(path) != 4
                    or any(node['tag'] != tag or node['class_name'] != class_name or node['role'] != ''
                        or node['tabindex'] != '' or node['cursor'] != (first_cursor if index == 0 else 'auto')
                        or node['pointer_events'] != 'auto' or node['visible'] is not True
                        or node['is_cell'] is not (index == 3)
                        for index, (node, tag, class_name) in enumerate(zip(path, ['div', 'span', 'div', 'td'], classes)))):
                raise ValueError('fill_status_roleless_public_structure_changed')
        index = record['control_index']
        if (action['ancestors'][1:] != status['ancestors'][1:]
                or controls[index] != {'tag': 'div', 'role': '', 'text': '回填发文', 'visible': True}):
            raise ValueError('fill_status_roleless_control_binding_changed')
        result.add(index)
    return result


def validate_evidence(value):
    fields = {'schema', 'raw_visible_text', 'status_source', 'status_texts', 'controls',
              'cell_visible', 'truncated', 'canonical_status'}
    if not isinstance(value, dict) or value.get('schema') not in (SCHEMA, SCHEMA_V2):
        raise ValueError('fill_status_evidence_schema_invalid')
    v2 = value['schema'] == SCHEMA_V2
    if v2:fields = fields | {'roleless_action_evidence'}
    if set(value) not in (fields, fields | {'cell_structure'}):
        raise ValueError('fill_status_evidence_schema_invalid')
    if 'cell_structure' in value:
        _validate_structure(value['cell_structure'])
    raw, texts, controls = value['raw_visible_text'], value['status_texts'], value['controls']
    if (not isinstance(raw, str) or len(raw) > 512 or not isinstance(texts, list) or len(texts) > 16
            or any(not isinstance(x, str) or not x or len(x) > 256 for x in texts)
            or not isinstance(controls, list) or len(controls) > 8
            or value['status_source'] != ('visible_non_action_text_nodes' if v2 else 'visible_noninteractive_text_nodes')
            or type(value['cell_visible']) is not bool or type(value['truncated']) is not bool):
        raise ValueError('fill_status_evidence_fields_invalid')
    roleless = _roleless_controls(value['roleless_action_evidence'], controls) if v2 else set()
    for index, control in enumerate(controls):
        if (not isinstance(control, dict) or set(control) != {'tag', 'role', 'text', 'visible'}
                or not isinstance(control['tag'], str) or len(control['tag']) > 20
                or not isinstance(control['role'], str) or len(control['role']) > 30
                or not isinstance(control['text'], str) or len(control['text']) > 256
                or control['visible'] is not True
                or not (control['tag'] in ('a', 'button') or control['role'] in ('button', 'link') or index in roleless)):
            raise ValueError('fill_status_control_evidence_invalid')
    suffix = ''.join(x['text'] for x in controls)
    compact = lambda text: re.sub(r'\s', '', text)
    raw_matches = compact(raw) in {compact(''.join(texts) + suffix), compact(suffix + ''.join(texts))}
    supported = (value['cell_visible'] and not value['truncated'] and texts == ['未填写']
                 and len(controls) <= 1 and all(x['text'] == '回填发文' for x in controls) and raw_matches)
    canonical = '未填写' if supported else None
    if value['canonical_status'] != canonical:
        raise ValueError('fill_status_evidence_semantics_changed')
    return canonical


def normalize_row(source):
    """Return the original status unless this row carries the new exact proof."""
    if 'fill_status_evidence' not in source:
        return source.get('fill_status'), None
    evidence = source['fill_status_evidence']
    canonical = validate_evidence(evidence)
    expected = canonical if canonical is not None else evidence['raw_visible_text']
    # A hidden-only cell can have empty innerText but nonempty textContent.
    # Such an unsupported proof must never regain the exact unfilled state.
    if canonical is None and expected == '未填写':
        expected = '未确认'
    if source.get('fill_status') != expected:
        raise ValueError('fill_status_row_and_evidence_disagree')
    return expected, deepcopy(evidence)
