"""Observed Fanqie batch form adapter; caller owns session, identity and lease.

Does not create browsers or copy authentication. Uses page UI rather than
guessing private API versions/enums. Real posting still requires live acceptance.
"""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urljoin, urlsplit

from src.services.fanqie_backfill_workflow import BackfillBlocked


PROMOTION_LIST_URL = "https://kol.fanqieopen.com/page/promotion-list?tab_type=2&top_tab_genre=-1"
BATCH_HISTORY_URL = "https://kol.fanqieopen.com/page/batch-history"
OFFICIAL_TEMPLATE_URL = "https://lf3-reading.fqnovelstatic.com/obj/novel-static/34feab9a366dc5cba9aec875f96b54f7.xlsx"
STABLE_FIELDS = ('alias_id', 'platform_task_id', 'promotion_path')
IDENTITY_ATTRIBUTES = {
    'data-alias-id': 'alias_id', 'data-promotion-alias-id': 'alias_id',
    'data-platform-task-id': 'platform_task_id', 'data-promotion-task-id': 'platform_task_id',
    'data-task-id': 'platform_task_id', 'data-promotion-path': 'promotion_path',
}
IDENTITY_QUERY_KEYS = {
    'alias_id': 'alias_id', 'aliasId': 'alias_id',
    'platform_task_id': 'platform_task_id', 'promotion_task_id': 'platform_task_id',
    'task_id': 'platform_task_id', 'taskId': 'platform_task_id',
    'promotion_path': 'promotion_path', 'promotionPath': 'promotion_path',
}
IDENTITY_COLUMNS = {'别名ID': 'alias_id', '任务ID': 'platform_task_id',
                    '推广任务ID': 'platform_task_id', '推广路径': 'promotion_path'}


def _value(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    value = str(value).strip()
    return value if value and len(value) <= 512 and not any(ord(c) < 32 for c in value) else None


def _response_rows(capture, now, context):
    """Optional owner-captured response; never fetch or guess an endpoint.

    A capture is useful only if its native JSON file is SHA-pinned and fresh.
    Unrecognized response shapes are deliberately not searched heuristically.
    """
    if capture is None:
        return []
    fields = ('resource_id', 'platform_identity_key', 'environment_key', 'owner_id', 'generation')
    if (not isinstance(context, dict) or any(not isinstance(context.get(k), str) or not context[k]
            for k in fields[:-1]) or type(context.get('generation')) is not int or context['generation'] < 1
            or any(capture.get(k) != context[k] for k in fields)):
        raise BackfillBlocked('promotion_response_managed_context_required')
    if capture.get('schema') != 'fanqie_promotion_response_capture/v1':
        raise BackfillBlocked('unsupported_promotion_response_capture')
    parsed = urlsplit(capture.get('url', ''))
    if (parsed.scheme != 'https' or parsed.netloc != 'kol.fanqieopen.com'
            or capture.get('http_status') != 200 or not isinstance(capture.get('observed_at'), (int, float))
            or not 0 <= now - capture['observed_at'] <= 60):
        raise BackfillBlocked('stale_or_foreign_promotion_response')
    binding = capture.get('body', {})
    path = Path(binding.get('path', ''))
    if (not path.is_absolute() or not path.resolve().is_relative_to(Path(__file__).resolve().parents[2])
            or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != binding.get('sha256')):
        raise BackfillBlocked('promotion_response_body_changed')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if isinstance(value, dict) and isinstance(value.get('data'), dict):
        value = value['data']
    records = next((value[k] for k in ('items', 'list', 'rows')
                    if isinstance(value, dict) and isinstance(value.get(k), list)), [])
    return [dict(row, _response_body=binding, _response_url=capture['url'])
            for row in records if isinstance(row, dict)]


def normalize_promotion_rows(value, *, response_capture=None, response_context=None, now=None):
    """Resolve explicit native identities; row index/title/alias never become IDs."""
    now = time.time() if now is None else now
    records = _response_rows(response_capture, now, response_context)
    result = dict(value)
    normalized = []
    for original in value.get('items', []):
        row = dict(original)
        sources = {field: [] for field in STABLE_FIELDS}
        for item in row.get('identity_attributes', []):
            field = IDENTITY_ATTRIBUTES.get(item.get('name'))
            v = _value(item.get('value'))
            if field and v:
                sources[field].append(dict(kind='dom_attribute', key=item['name'], value=v))
        for item in row.get('identity_columns', []):
            field, v = IDENTITY_COLUMNS.get(item.get('header')), _value(item.get('value'))
            if field and v:
                sources[field].append(dict(kind='dom_column', key=item['header'], value=v))
        for href in row.get('identity_links', []):
            parsed = urlsplit(urljoin(PROMOTION_LIST_URL, href))
            if parsed.scheme != 'https' or parsed.netloc != 'kol.fanqieopen.com':
                continue
            for key, values in parse_qs(parsed.query).items():
                field = IDENTITY_QUERY_KEYS.get(key)
                if field:
                    for raw in values:
                        v = _value(raw)
                        if v:
                            sources[field].append(dict(kind='href_query', key=key, value=v,
                                url=urljoin(PROMOTION_LIST_URL, href)))
        matching = [r for r in records if str(r.get('book_id', '')) == row.get('book_id')
                    and r.get('alias', r.get('promotion_alias')) == row.get('alias')
                    and r.get('publish_type') == row.get('publish_type')]
        if len(matching) > 1:
            raise BackfillBlocked('ambiguous_platform_promotion_record')
        if matching:
            record = matching[0]
            for field in STABLE_FIELDS:
                v = _value(record.get(field))
                if v:
                    sources[field].append(dict(kind='platform_response', key=field, value=v,
                        body=record['_response_body'], url=record['_response_url']))
        missing, conflict = [], []
        for field in STABLE_FIELDS:
            values = {s['value'] for s in sources[field]}
            # Ignore caller-prepopulated IDs which have no explicit source.
            row.pop(field, None)
            if len(values) == 1:
                row[field] = next(iter(values))
            elif not values:
                missing.append(field)
            else:
                conflict.append(field)
        row['stable_identity_evidence'] = sources
        row['stable_identity_status'] = 'verified' if not missing and not conflict else 'needs_sync'
        row['missing_identity_fields'], row['conflicting_identity_fields'] = missing, conflict
        normalized.append(row)
    result['items'] = normalized
    return result


class _HTMLNode:
    def __init__(self, tag, attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
    def all(self, tag=None):
        for child in self.children:
            if isinstance(child, _HTMLNode):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.all(tag)
    def text(self):
        return ' '.join(''.join(c.text() if isinstance(c, _HTMLNode) else c
                               for c in self.children).split())


class _FixtureHTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.root = _HTMLNode('root'); self.stack = [self.root]
    def handle_starttag(self, tag, attrs):
        node = _HTMLNode(tag, attrs); self.stack[-1].children.append(node)
        if tag not in {'meta', 'link', 'input', 'br', 'hr', 'img'}:
            self.stack.append(node)
    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]; break
    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_promotion_html(html, *, response_capture=None, response_context=None, now=None):
    """Offline fixture/parser API using the same explicit-ID normalization."""
    parser = _FixtureHTML(); parser.feed(html)
    required = ['关键词', '书本信息', '发文类型', '别名状态', '书籍状态', '发文详情']
    tables = []
    for table in parser.root.all('table'):
        headers = [n.text() for n in table.all('th')]
        if all(headers.count(h) == 1 for h in required):
            tables.append((table, headers))
    if len(tables) != 1:
        return dict(table_ready=False, items=[])
    table, heads = tables[0]; rows = []
    for tr in table.all('tr'):
        cells = [n for n in tr.children if isinstance(n, _HTMLNode) and n.tag == 'td']
        if len(cells) != len(heads):
            continue
        cell = dict(zip(heads, cells)); raw = cell['书本信息'].text()
        book_id = re.search(r'\bid\s*[:：]\s*(\d{10,24})', raw, re.I)
        nodes = [tr, *tr.all()]
        links = [n.attrs['href'] for n in nodes if n.tag == 'a' and n.attrs.get('href')]
        details = cell['发文详情'].text()
        post_links = [n.attrs['href'] for n in cell['发文详情'].all('a') if n.attrs.get('href')]
        post_links += re.findall(r'https://www\.douyin\.com/video/\d{10,24}', details)
        rows.append(dict(alias=cell['关键词'].text(), book_id=book_id[1] if book_id else '',
            book_name=re.sub(r'\s*id\s*[:：].*$', '', raw, flags=re.I).strip(),
            valid_range=cell['有效期'].text() if '有效期' in cell else '',
            publish_type=cell['发文类型'].text(), alias_status=cell['别名状态'].text(),
            book_status=cell['书籍状态'].text(), fill_status=details,
            published_links=sorted(set(u for u in post_links if re.fullmatch(r'https://www\.douyin\.com/video/\d{10,24}', u))),
            identity_links=links, identity_attributes=[dict(name=k, value=v) for n in nodes
                for k, v in n.attrs.items() if k in IDENTITY_ATTRIBUTES],
            identity_columns=[dict(header=k, value=cell[k].text()) for k in IDENTITY_COLUMNS if k in cell]))
    return normalize_promotion_rows(dict(table_ready=True, items=rows), response_capture=response_capture,
                                    response_context=response_context, now=now)

OBSERVE_ROWS_JS = r"""() => {
  const text = e => (e?.innerText || e?.textContent || '').trim();
  const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
  const required = ['关键词','书本信息','发文类型','别名状态','书籍状态','发文详情'];
  const tables = Array.from(document.querySelectorAll('table')).filter(visible).filter(t => {
    const heads = Array.from(t.querySelectorAll('thead th')).map(text);
    return required.every(h => heads.includes(h));
  });
  if(tables.length !== 1) return {table_ready:false,items:[]};
  const table=tables[0], heads=Array.from(table.querySelectorAll('thead th')).map(text);
  if(required.some(h=>heads.filter(x=>x===h).length!==1)) return {table_ready:false,items:[]};
  const items=Array.from(table.querySelectorAll('tbody tr')).filter(visible).map(row=>{
    const cells=Array.from(row.querySelectorAll('td'));
    const cell=h=>cells[heads.indexOf(h)];
    const book=text(cell('书本信息')), match=book.match(/\bid\s*[:：]\s*(\d{10,24})/i);
    const detail=cell('发文详情');
    const urls=Array.from(detail?.querySelectorAll('a[href]')||[]).map(a=>a.href);
    urls.push(...(text(detail).match(/https:\/\/www\.douyin\.com\/video\/\d{10,24}/g)||[]));
    const keys=['data-alias-id','data-promotion-alias-id','data-platform-task-id',
      'data-promotion-task-id','data-task-id','data-promotion-path'];
    const identity_attributes=[];
    for(const node of [row,...row.querySelectorAll('*')]) for(const key of keys) {
      const v=node.getAttribute(key); if(v) identity_attributes.push({name:key,value:v});
    }
    return {alias:text(cell('关键词')),book_id:match?match[1]:'',book_name:book.replace(/\s*id\s*[:：].*$/i,'').trim(),
      valid_range:text(cell('有效期')),publish_type:text(cell('发文类型')),
      alias_status:text(cell('别名状态')),book_status:text(cell('书籍状态')),fill_status:text(detail),
      identity_attributes,identity_links:Array.from(row.querySelectorAll('a[href]')).map(a=>a.href),
      identity_columns:heads.map((header,i)=>({header,value:text(cells[i])})),
      published_links:Array.from(new Set(urls.filter(u=>/^https:\/\/www\.douyin\.com\/video\/\d{10,24}$/.test(u))))};
  });
  return {table_ready:true,items};
}"""


class FanqieBatchPageAdapter:
    def __init__(self, page, *, identity_probe, response_capture=None, response_context=None, require_fresh_identity=False):
        self.page = page
        # Must independently return {account, verified, challenge}; no default
        # based on a display nickname or user's supplied account string.
        self.identity_probe = identity_probe
        self.response_capture = response_capture
        self.response_context = response_context
        self.require_fresh_identity = require_fresh_identity
        self._submitted = False

    def _check(self, binding):
        url = urlsplit(self.page.url)
        if (url.scheme != "https" or url.netloc != "kol.fanqieopen.com" or
                url.path != "/page/promotion-list" or parse_qs(url.query).get("tab_type") != ["2"]):
            raise BackfillBlocked("original_fanqie_list_required")
        identity = self.identity_probe(self.page)
        if (identity.get("account") != binding.fanqie_account or identity.get("verified") is not True
                or identity.get("challenge") is not False):
            raise BackfillBlocked("original_fanqie_identity_or_challenge")
        if self.require_fresh_identity and (not isinstance(identity.get('observed_at'), (int, float))
                or not 0 <= time.time() - identity['observed_at'] <= 60):
            raise BackfillBlocked('stale_fanqie_adapter_identity')

    def observe(self, binding):
        self._check(binding)
        if self._submitted:
            # Reread the server-backed list, never trust a generic success toast.
            self.page.reload(wait_until="domcontentloaded")
            self._check(binding)
        value = {"table_ready": False, "items": []}
        for _ in range(6):
            self._check(binding)
            value = self.page.evaluate(OBSERVE_ROWS_JS)
            if value.get("table_ready"):
                break
            self.page.wait_for_timeout(500)
        value = normalize_promotion_rows(value,
            response_capture=self.response_capture(self.page) if self.response_capture else None,
            response_context=self.response_context() if self.response_context else None)
        return dict(value, account=binding.fanqie_account, identity_verified=True,
                    challenge=False, observed_at=time.time())

    def _dialog(self):
        dialog = self.page.get_by_role("dialog", name="批量上传发文-番茄小说", exact=True)
        if dialog.count() != 1 or not dialog.is_visible():
            raise BackfillBlocked("unique_backfill_dialog_required")
        return dialog

    def upload(self, workbook, binding):
        self._check(binding)
        button = self.page.get_by_role("button", name="批量回填发文", exact=True)
        if button.count() != 1:
            raise BackfillBlocked("unique_batch_entry_required")
        button.click()
        dialog = self._dialog()
        upload = dialog.locator('input[type="file"]')
        if upload.count() != 1:
            raise BackfillBlocked("unique_backfill_file_input_required")
        self._check(binding)
        upload.set_input_files(workbook)
        self._ready_submit(binding)
        return {"upload_ready": True, "source": "submit_control_enabled"}

    def _ready_submit(self, binding):
        self._check(binding)
        button = self._dialog().get_by_role("button", name="提交", exact=True)
        if button.count() != 1:
            raise BackfillBlocked("unique_backfill_submit_required")
        for _ in range(20):
            self._check(binding)
            if button.is_enabled():
                return button
            self.page.wait_for_timeout(500)
        raise BackfillBlocked("backfill_upload_not_ready")

    def submit(self, binding):
        button = self._ready_submit(binding)
        self._submitted = True
        button.click()
