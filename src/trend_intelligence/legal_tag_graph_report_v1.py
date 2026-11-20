"""Readable, offline views of a source-bound legal metadata relationship graph."""
from __future__ import annotations

from collections import Counter
import html
import json
from typing import Any

ROLE_LABELS = {
    'legal_issue': '法律议题', 'legal_procedure': '程序与维权', 'legal_rule': '规则条文',
    'legal_outcome': '结果与补偿', 'audience_context': '受众处境',
    'domain_generic': '泛法律标签', 'campaign': '活动标签', 'creator_brand': '作者或推广',
    'location': '地域', 'generic_noise': '泛标签或无关', 'ambiguous': '待核对',
}
EDGE_LABELS = {'tag_cooccurrence': '同视频标签共现', 'keyword_hashtag': '搜索词 → 标签',
               'taxonomy_related': '词表相关概念（非同义）'}


def _md(value: Any) -> str:
    return str(value).replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')


def _metrics(documents: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(d.get('metric_kind', 'unknown') for d in documents)
    totals = {}
    for kind in ('likes', 'views'):
        values = [d['metric_value'] for d in documents if d.get('metric_kind') == kind and d.get('metric_value') is not None]
        if values:
            totals[kind] = sum(values)
    return {'video_counts_by_metric_kind': dict(counts), 'deduplicated_observed_totals': totals}


def render_report(graph: dict[str, Any], candidates: list[dict[str, Any]], packet: dict[str, Any], *, prepared_at: str) -> str:
    """All counts come from the exact graph; never imply a production result."""
    summary, chosen = graph['summary'], packet['candidate']
    labels = {n['tag_id']: n['label'] for n in graph['nodes']}
    labels.update({n['keyword_id']: n['label'] for n in graph['keywords']})
    metrics = _metrics(graph['documents'])
    lines = ['# 法律标签族、关系图谱与创作输入', '',
        f'离线导出时间：{prepared_at}。采集批次：`{graph["collection_run_id"]}`。', '',
        f'本报告使用原批次 {_md(summary["observation_count"])} 条观测，按原视频去重为 {_md(summary["unique_video_count"])} 个视频；'
        f'原始标签字形 {_md(summary["raw_hashtag_label_count"])} 种，归一后 {_md(summary["normalized_tag_count"])} 个标签节点。', '',
        '## 这次实际补齐的部分', '',
        f'- 标签实际归属：{summary["nonempty_family_count"]} 个有成员的检索标签族，保留每个成员的分类规则与支持视频。',
        f'- 标签关系：{summary["edge_counts"].get("tag_cooccurrence", 0)} 条同视频标签共现；其中 '
        f'{summary["creative_eligible_cooccurrence_count"]} 条符合至少 2 个视频、2 个可见作者名及议题角色要求。',
        f'- 搜索证据：{summary["edge_counts"].get("keyword_hashtag", 0)} 条搜索词到标签关系，独立于标签共现。',
        f'- 词表关系：{summary["edge_counts"].get("taxonomy_related", 0)} 条相关概念关系，不作为同义或法律等价证据。',
        '- 将实际候选的有限共现邻域、标签族与全批次摘要写入方向请求和真实传输格式的离线预览。完整图另存并绑定哈希。',
        '- 原始采集、旧机会、旧请求、调用与消耗记录未迁移或覆盖；本次没有采集、模型、媒体或发布调用。', '',
        '## 实际标签族', '',
        '| 检索标签族 | 成员标签 | 去重支持视频 | 可见作者名 | 达证据门槛标签 |',
        '|---|---:|---:|---:|---:|']
    for family in graph['families']:
        lines.append(f'| {_md(family["label"])} | {len(family["member_tag_ids"])} | {family["support_video_count"]} | '
                     f'{family["visible_author_count"]} | {family["creative_eligible_member_count"]} |')
    lines += ['', '同一视频可以支持多个标签族，表中数量不能相加当成批次总视频数。分类为显式检索规则，不宣称自动发现法律语义。', '',
              '## 标签角色隔离', '', '| 角色 | 标签数 | 是否可作核心选题 |', '|---|---:|---|']
    for role, count in summary['role_counts'].items():
        eligible = '议题标签符合支持门槛时可作核心；其他角色只作相关信息' if role == 'legal_issue' else (
            '符合门槛时可作相关信息' if role in {'legal_procedure', 'legal_rule', 'legal_outcome', 'audience_context'} else '否；保留原始证据供核对')
        lines.append(f'| {_md(ROLE_LABELS.get(role, role))} | {count} | {eligible} |')
    lines += ['', '活动话题、律师或地点推广、泛法律词与未分类词不会因同现频率高就成为故事核心。', '',
        '## 当前选择与下游边界', '',
        f'本轮维持已讨论的受众议题 **{_md(chosen["title"])}**，由 **{chosen["support_video_count"]} 个视频、'
        f'{chosen["visible_author_count"]} 个可见作者名**支持；不是沿用旧机会的单一来源。', '',
        '这些视频的标签只证明此受众议题出现在样本中。它们不能证明“人事催签自愿离职”这一原创情节、具体个案违法或案件结果；'
        '“被迫离职”来源中涉及劳动者解除劳动合同的情形，与雇主催签并非同一事实。故事方向仍需人确认。', '',
        '相关标签按实际同视频关系选择，最多 6 个；避免把整个劳动标签族拼进剧情：', '',
        '| 相关标签 | 与核心同现视频 | 同现可见作者名 | Jaccard |', '|---|---:|---:|---:|']
    for tag in chosen['related_tags']:
        lines.append(f'| {_md(tag["label"])} | {tag["support_video_count"]} | {tag["visible_author_count"]} | {tag["jaccard"]:.4f} |')
    lines += ['', '候选排序是透明的检索排序，不是热度增长、法律成立或创作质量评分。完整候选见 [CANDIDATES.json](CANDIDATES.json)。', '',
        '## 本批次支持视频较多的共现', '',
        '| 标签 A | 标签 B | 同现视频 | 可见作者名 | Jaccard | lift | NPMI |',
        '|---|---|---:|---:|---:|---:|---:|']
    edges = sorted((e for e in graph['edges'] if e['relation_kind'] == 'tag_cooccurrence' and e['creative_eligible']),
                   key=lambda e: (-e['support_video_count'], -e['visible_author_count'], e['source'], e['target']))[:15]
    for edge in edges:
        lines.append(f'| {_md(labels[edge["source"]])} | {_md(labels[edge["target"]])} | {edge["support_video_count"]} | '
                     f'{edge["visible_author_count"]} | {edge["jaccard"]:.4f} | {edge["lift"]:.4f} | {edge["npmi"]:.4f} |')
    lines += ['', f'共现统计总体固定为 {summary["unique_video_count"]} 个去重视频。高 lift 的稀有关系仍需数量和作者门槛；'
        '上述关系不是因果关系，不能推导法律适用。', '', '## 字形、同义与冲突概念', '',
        '仅合并 Unicode 字形和英文大小写变体；不擅自合并法律概念。经济补偿/赔偿、定金/订金、离职/辞退、'
        '被迫离职/被迫解除保持不同节点。词表相关边与实际共现边分开保存。', '', '## 指标与证据范围', '',
        f'按原视频去重后的指标分布：`{json.dumps(metrics["video_counts_by_metric_kind"], ensure_ascii=False, sort_keys=True)}`。', '',
        f'同种指标的最小观测值合计：`{json.dumps(metrics["deduplicated_observed_totals"], ensure_ascii=False, sort_keys=True)}`。', '',
        '点赞和播放不混加；重复查询的同一视频只计一次。此数是本批可见指标，不能当成平台总流量、时间增长或全站热度。'
        '原始视频没有听看、ASR 或剧情分析；标题中的主张仍是未核验元数据。', '', '## 可直接核对的产物', '',
        '- [互动关系图与全部支持证据](GRAPH.html)：按标签族、角色、关系类型和数量过滤，点击节点或边查看原始支持视频链接。',
        '- [完整关系图 JSON](GRAPH.json)、[图谱候选](CANDIDATES.json)、[来源和图谱冻结包](SOURCE_PACKET.json)。',
        '- [方向请求预览](DIRECTION_REQUEST_PREVIEW.json)、[传输格式预览](DIRECTION_WIRE_PREVIEW.json)、[文件哈希清单](MANIFEST.json)。', '',
        '本次只达到离线分析与请求接线验证。两个请求预览均 `submitted=false`、`dispatch_allowed=false`；'
        '没有新增真实服务回执、完整剧本、导演安排、逐拍表演、制作交接或创作质量通过记录。', '',
        '下一步由本图谱的具体受众议题生成或修订完整故事方向，用户确认后提交完整新稿并全文审查；'
        '不能将旧方向确认静默继承到新的图谱输入。', '']
    return '\n'.join(lines)


def render_graph_html(graph: dict[str, Any], candidates: list[dict[str, Any]], packet: dict[str, Any], *, prepared_at: str) -> str:
    """Standalone local HTML: no network, media requests, eval, or metadata HTML."""
    payload = {'graph': graph, 'candidates': candidates, 'selected': packet['candidate'], 'prepared_at': prepared_at,
               'role_labels': ROLE_LABELS, 'edge_labels': EDGE_LABELS}
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return HTML_TEMPLATE.replace('__GRAPH_DATA__', data).replace('__TITLE__', html.escape('法律号：标签族与证据关系图'))


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'none'; connect-src 'none'; media-src 'none'; object-src 'none'; base-uri 'none'">
<style>
:root{color-scheme:light;--ink:#12283a;--muted:#566d7a;--paper:#f4f7fa;--line:#d8e3eb;--accent:#0a7777}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 system-ui,'Microsoft YaHei',sans-serif}main{max-width:1400px;margin:auto;padding:32px}h1{font-size:30px;margin:0 0 8px}h2{font-size:20px;margin:0 0 12px}p{margin:8px 0}small,.muted{color:var(--muted)}.card{background:white;border:1px solid var(--line);border-radius:14px;padding:20px;margin:18px 0}.banner{background:#e5f5f1;border-left:5px solid var(--accent)}.warning{background:#fff5dd;border-left:5px solid #c58919}.metrics{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-top:18px}.metric{background:white;border:1px solid var(--line);border-radius:12px;padding:14px}.metric strong{display:block;font-size:28px}.controls{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin:12px 0}label{display:flex;gap:7px;align-items:center}select,input,button{font:inherit;padding:7px 10px;border:1px solid #bdceda;border-radius:6px;background:white;color:var(--ink)}input[type=number]{width:75px}input[type=search]{min-width:230px}button{cursor:pointer;background:#e5f5f1}.columns{display:grid;grid-template-columns:minmax(0,2fr) minmax(280px,1fr);gap:20px}.graph{border:1px solid var(--line);background:#f9fcfd;border-radius:10px;overflow:hidden}svg{width:100%;height:560px;display:block}.details{max-height:560px;overflow:auto;font-size:14px}.detail-doc{border-top:1px solid var(--line);padding:8px 0}.chip{display:inline-block;border-radius:5px;padding:1px 6px;background:#e8eff4;margin:2px;font-size:12px}.tablewrap{overflow:auto;max-height:460px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;border-bottom:1px solid var(--line);padding:9px 10px;vertical-align:top}th{position:sticky;top:0;background:#edf3f7}tr.clickable{cursor:pointer}tr.clickable:hover{background:#edf7f5}a{color:#086d79;word-break:break-all}.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px}.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}.count{font-weight:600;color:#086d79}@media(max-width:900px){main{padding:18px}.columns{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}svg{height:460px}}
</style></head><body><main><h1>法律号：标签族与证据关系图</h1><p class="muted" id="meta"></p>
<div class="card banner"><strong>图谱用于选题检索与来源核对。</strong><p>同视频共现、搜索词关系、词表相关概念是三种证据。它们不能证明法律适用、情节真实性、平台总热度或创作质量。完整图在本页离线加载；不请求原视频或外部服务。</p></div>
<div class="metrics" id="metrics"></div>
<div class="card warning" id="selection"></div>
<section class="card"><h2>关系图</h2><div class="controls"><label>标签族 <select id="family"></select></label><label>标签角色 <select id="role"></select></label><label>关系类型 <select id="kind"></select></label><label>最少视频 <input id="min" type="number" min="0" value="2"></label><label>图面最多节点 <input id="limit" type="number" min="10" max="150" value="50"></label><label><input id="eligible" type="checkbox" checked>只看达证据门槛关系</label><input id="search" type="search" placeholder="搜索标签、标题、作者名"><button id="reset">重置</button></div><p class="muted">图面按支持数截取，标签与关系表包含过滤后的全部数据。查询节点用方形，标签用圆形；线表示所选关系类型。点击任意节点或边查看支持证据。</p><div class="legend" id="legend"></div><p id="graph-count" class="count"></p><div class="columns"><div class="graph"><svg id="svg" viewBox="0 0 980 560" role="img" aria-label="标签关系图"></svg></div><aside class="details" id="details"><h2>支持证据</h2><p>点击节点或关系行，查看来源视频、标题和标签。标题中的法律断言未经本模块核验。</p></aside></div></section>
<section class="card"><h2>标签族</h2><div class="tablewrap"><table><thead><tr><th>标签族</th><th>成员标签</th><th>去重支持视频</th><th>可见作者名</th><th>达证据门槛标签</th></tr></thead><tbody id="families"></tbody></table></div><p class="muted">视频可属于多个检索标签族，不能加总为批次总量。显式词表分类保留规则名称，并非自动语义聚类。</p></section>
<section class="card"><h2>标签与角色 <span id="node-count" class="count"></span></h2><div class="tablewrap"><table><thead><tr><th>标签</th><th>角色与归属</th><th>去重视频</th><th>作者名</th><th>达到门槛</th><th>分类依据</th></tr></thead><tbody id="nodes"></tbody></table></div></section>
<section class="card"><h2>全部过滤关系 <span id="edge-count" class="count"></span></h2><div class="tablewrap"><table><thead><tr><th>来源</th><th>目标</th><th>关系</th><th>同现视频</th><th>作者名</th><th>Jaccard</th><th>lift</th><th>NPMI</th></tr></thead><tbody id="edges"></tbody></table></div></section>
<section class="card"><h2>全部来源视频 <span id="doc-count" class="count"></span></h2><div class="tablewrap"><table><thead><tr><th>原始标题与链接</th><th>可见作者名</th><th>观测标签</th><th>单视频指标</th><th>查询来源</th></tr></thead><tbody id="docs"></tbody></table></div><p class="muted">同一视频跨查询去重；同类指标取最小观测值；点赞与播放分开。这里只显示页面元数据，没有观看、听取或分析原始视频。</p></section>
<section class="card"><h2>检索候选</h2><div class="tablewrap"><table><thead><tr><th>受众议题</th><th>支持视频</th><th>可见作者名</th><th>相关标签</th><th>检索分</th></tr></thead><tbody id="candidates"></tbody></table></div><p class="muted">分数仅为支持数量、可见作者名及达到证据门槛的邻居的透明检索排序，不是内容质量或法律结论。</p></section>
<section class="card"><h2>限制与下游状态</h2><ul id="limitations"></ul><p><strong>离线预览已准备，未派发模型。</strong>提交标志为 false；新图谱不能继承旧方向确认。尚无本图谱对应的完整新剧本、全文审查、导演、逐拍表演、制作交接或创作质量通过。</p><p><a href="REPORT.md">报告</a> · <a href="GRAPH.json">完整图</a> · <a href="SOURCE_PACKET.json">冻结包</a> · <a href="DIRECTION_REQUEST_PREVIEW.json">方向请求预览</a> · <a href="DIRECTION_WIRE_PREVIEW.json">传输格式预览</a> · <a href="MANIFEST.json">哈希清单</a></p></section>
</main><script id="graph-data" type="application/json">__GRAPH_DATA__</script><script>
'use strict';const D=JSON.parse(document.getElementById('graph-data').textContent),G=D.graph,N=new Map(G.nodes.map(n=>[n.tag_id,n])),K=new Map(G.keywords.map(n=>[n.keyword_id,n])),F=new Map(G.families.map(f=>[f.family_id,f.label])),DOC=new Map(G.documents.map(d=>[d.video_id,d])),S='http://www.w3.org/2000/svg';const colors={legal_issue:'#0a7777',legal_procedure:'#496bc5',legal_rule:'#9665b7',legal_outcome:'#c17a26',audience_context:'#678f42',campaign:'#a9a9a9',creator_brand:'#b26a82',domain_generic:'#748995',generic_noise:'#a9a9a9',location:'#a58f78',ambiguous:'#9d8f72',keyword:'#213f57'};
const el=id=>document.getElementById(id),txt=(tag,text,klass)=>{let n=document.createElement(tag);n.textContent=String(text??'');if(klass)n.className=klass;return n;},append=(node,...items)=>items.forEach(i=>node.append(i)),label=id=>N.get(id)?.label||K.get(id)?.label||id,fmt=n=>n==null?'—':Number(n).toFixed(4),opt=(select,value,text)=>{let o=txt('option',text);o.value=value;select.append(o);},cell=(row,text)=>row.append(txt('td',text));function safeLink(url,text){let a=txt('a',text);try{let u=new URL(url);if(['http:','https:'].includes(u.protocol)){a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';}}catch{}return a;}
el('meta').textContent=`导出 ${D.prepared_at} · 批次 ${G.collection_run_id} · 元数据范围`;[['去重视频',G.summary.unique_video_count],['标签节点',G.summary.normalized_tag_count],['有成员标签族',G.summary.nonempty_family_count],['全部标签共现',G.summary.edge_counts.tag_cooccurrence||0],['达证据门槛标签共现',G.summary.creative_eligible_cooccurrence_count]].forEach(([t,v])=>{let x=txt('div','','metric');append(x,txt('strong',v),txt('small',t));el('metrics').append(x);});const chosen=D.selected;append(el('selection'),txt('strong',`本轮受众议题：${chosen.title} · ${chosen.support_video_count} 个支持视频 / ${chosen.visible_author_count} 个可见作者名`),txt('p','标签只证明样本受众关切，不能验证“人事催签自愿离职”的原创剧情；被迫离职的部分来源涉及劳动者主动解除情形。法律依据与故事确认分别处理。'));
opt(el('family'),'','全部标签族');G.families.forEach(f=>opt(el('family'),f.family_id,`${f.label}（${f.support_video_count} 视频）`));el('family').value=chosen.family_id;opt(el('role'),'','全部角色');Object.entries(D.role_labels).forEach(([r,l])=>opt(el('role'),r,l));Object.entries(D.edge_labels).forEach(([r,l])=>opt(el('kind'),r,l));el('kind').value='tag_cooccurrence';Object.entries(D.role_labels).forEach(([r,l])=>{let x=txt('span');let i=document.createElement('i');i.style.background=colors[r];append(x,i,txt('span',l));el('legend').append(x);});G.families.forEach(f=>{let r=document.createElement('tr');[f.label,f.member_tag_ids.length,f.support_video_count,f.visible_author_count,f.creative_eligible_member_count].forEach(v=>cell(r,v));el('families').append(r);});G.limitations.forEach(l=>el('limitations').append(txt('li',l)));
function docItem(d){let x=txt('div','','detail-doc');append(x,txt('strong',d.titles.join(' / ')||d.video_id),txt('p',`作者名：${d.author_names.join('、')||'未观测'}；标签：${d.hashtag_labels.join('、')}`));d.urls.forEach(url=>x.append(safeLink(url,'打开原始来源链接')));append(x,txt('small',` 原视频 ${d.video_id}； ${d.metric_kind} ${d.metric_value??'未知'}`));return x;}
function details(title,paragraphs,ids){let out=el('details');out.replaceChildren(txt('h2',title));paragraphs.forEach(p=>out.append(txt('p',p)));append(out,txt('p',`${ids.length} 个原视频支持；作者名仅为可见显示名。标题中的主张未经本模块核验。`));ids.forEach(id=>{if(DOC.has(id))out.append(docItem(DOC.get(id)));});}
function showNode(id){let n=N.get(id)||K.get(id);if(!n)return;details(n.label,[N.has(id)?`角色：${D.role_labels[n.role]||n.role}；分类依据：${n.classification_basis}`:'搜索词节点：表明该查询中观测到视频，不等于视频使用了这个标签。',`支持 ${n.support_video_count} 个视频`],n.support_video_ids);}
function showEdge(e){details(`${label(e.source)} → ${label(e.target)}`,[D.edge_labels[e.relation_kind],`证据依据：${e.relation_basis}`,`Jaccard ${fmt(e.jaccard)}；lift ${fmt(e.lift)}；NPMI ${fmt(e.npmi)}`],e.support_video_ids);}
function matches(n,q){return !q||[n.label,...(n.raw_labels||[]),...(n.support_video_ids||[]).flatMap(id=>{let d=DOC.get(id);return d?[...d.titles,...d.author_names]:[];})].some(x=>String(x).toLocaleLowerCase().includes(q));}
function svgNode(tag,attrs={}){let x=document.createElementNS(S,tag);Object.entries(attrs).forEach(([k,v])=>x.setAttribute(k,v));return x;}
function render(){const family=el('family').value,role=el('role').value,kind=el('kind').value,min=Math.max(0,Number(el('min').value)||0),q=el('search').value.trim().toLocaleLowerCase(),eligible=el('eligible').checked;let nodes=G.nodes.filter(n=>(!family||n.family_ids.includes(family))&&(!role||n.role===role)&&n.support_video_count>=min&&(!eligible||n.creative_eligible)&&matches(n,q));const ids=new Set(nodes.map(n=>n.tag_id));let edges=G.edges.filter(e=>e.relation_kind===kind&&e.support_video_count>=min&&(!eligible||e.creative_eligible)&&(kind==='keyword_hashtag'?ids.has(e.target):ids.has(e.source)&&ids.has(e.target))).sort((a,b)=>b.support_video_count-a.support_video_count||a.edge_id.localeCompare(b.edge_id));nodes.sort((a,b)=>b.support_video_count-a.support_video_count||a.label.localeCompare(b.label));el('node-count').textContent=`（${nodes.length}）`;el('edge-count').textContent=`（${edges.length}）`;el('nodes').replaceChildren();nodes.forEach(n=>{let r=document.createElement('tr');r.className='clickable';r.onclick=()=>showNode(n.tag_id);[n.label,`${D.role_labels[n.role]} · ${n.family_ids.map(id=>F.get(id)).join(' / ')||'未归属'}`,n.support_video_count,n.visible_author_count,n.creative_eligible?'是':'否',n.classification_basis].forEach(v=>cell(r,v));el('nodes').append(r);});el('edges').replaceChildren();edges.forEach(e=>{let r=document.createElement('tr');r.className='clickable';r.onclick=()=>showEdge(e);[label(e.source),label(e.target),D.edge_labels[e.relation_kind],e.support_video_count,e.visible_author_count,fmt(e.jaccard),fmt(e.lift),fmt(e.npmi)].forEach(v=>cell(r,v));el('edges').append(r);});const limit=Math.max(10,Math.min(150,Number(el('limit').value)||50));let shown=nodes.slice(0,limit).map(n=>({...n,id:n.tag_id}));if(kind==='keyword_hashtag'){const kid=[...new Set(edges.map(e=>e.source))];shown=[...kid.map(id=>({...K.get(id),id,role:'keyword'})),...shown.slice(0,Math.max(0,limit-kid.length))];}let pos=new Map(),size=shown.length;shown.forEach((n,i)=>{let t=(i/Math.max(1,size))*Math.PI*2-Math.PI/2,r=size>20?(i%2?170:245):205;pos.set(n.id,{x:490+Math.cos(t)*r,y:280+Math.sin(t)*r,n});});const svg=el('svg');svg.replaceChildren();let displayed=0;edges.forEach(e=>{let a=pos.get(e.source),b=pos.get(e.target);if(!a||!b)return;displayed++;let line=svgNode('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:kind==='taxonomy_related'?'#b78d56':'#7ba8b8','stroke-opacity':Math.min(.65,.18+e.support_video_count/35),'stroke-width':Math.min(7,1+Math.sqrt(e.support_video_count)/1.8)});if(kind==='taxonomy_related')line.setAttribute('stroke-dasharray','5 4');let t=svgNode('title');t.textContent=`${label(e.source)} / ${label(e.target)}：${e.support_video_count} 视频`;line.append(t);line.onclick=()=>showEdge(e);line.style.cursor='pointer';svg.append(line);});for(let {x,y,n}of pos.values()){let group=svgNode('g',{transform:`translate(${x},${y})`});group.style.cursor='pointer';group.onclick=()=>showNode(n.id);let r=5+Math.sqrt(n.support_video_count)*1.15;let shape=svgNode(n.role==='keyword'?'rect':'circle',n.role==='keyword'?{x:-r,y:-r,width:r*2,height:r*2,rx:3}:{r});shape.setAttribute('fill',colors[n.role]||'#7f8a99');shape.setAttribute('stroke','white');shape.setAttribute('stroke-width',2);let text=svgNode('text',{x:0,y:r+13,'text-anchor':'middle','font-size':n.label.length>10?9:11,fill:'#17364b'});text.textContent=n.label;let title=svgNode('title');title.textContent=`${n.label}：${n.support_video_count} 视频`;append(group,shape,text,title);svg.append(group);}el('graph-count').textContent=`当前过滤 ${nodes.length} 标签 / ${edges.length} 关系；图面显示 ${shown.length} 节点 / ${displayed} 关系。`;if(!shown.length){let t=svgNode('text',{x:490,y:280,'text-anchor':'middle',fill:'#566d7a'});t.textContent='当前筛选没有节点，可放宽数量或关闭达证据门槛关系过滤。';svg.append(t);}const docIds=new Set(nodes.flatMap(n=>n.support_video_ids));let docs=G.documents.filter(d=>docIds.has(d.video_id));if(!family&&!role&&!q&&min===0&&!eligible)docs=G.documents;el('doc-count').textContent=`（${docs.length}）`;el('docs').replaceChildren();docs.forEach(d=>{let r=document.createElement('tr'),c=document.createElement('td');append(c,txt('div',d.titles.join(' / ')||d.video_id));d.urls.forEach(u=>c.append(safeLink(u,'来源链接 ')));r.append(c);[d.author_names.join('、')||'未观测',d.hashtag_labels.join('、'),`${d.metric_kind} ${d.metric_value??'未知'}`,d.keywords.join('、')].forEach(v=>cell(r,v));el('docs').append(r);});}
D.candidates.forEach(c=>{let r=document.createElement('tr');r.className='clickable';r.onclick=()=>showNode(c.anchor_tag_id);[c.title,c.support_video_count,c.visible_author_count,c.related_tags.map(n=>n.label).join('、'),c.selection_score].forEach(v=>cell(r,v));el('candidates').append(r);});['family','role','kind','min','limit','eligible','search'].forEach(id=>el(id).addEventListener(id==='search'?'input':'change',render));el('reset').onclick=()=>{el('family').value='';el('role').value='';el('kind').value='tag_cooccurrence';el('min').value=0;el('limit').value=50;el('eligible').checked=false;el('search').value='';render();};render();
</script></body></html>'''
