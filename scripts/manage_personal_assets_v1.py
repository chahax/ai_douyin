"""Local discovery index only: never changes source assets, reviews, or production bindings."""
import argparse
import datetime as dt
import hashlib
import html
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/visual_asset_library/personal_catalog_v1'
LEGACY = 'data/visual_asset_library/reusable_assets.json'
BOARDS = 'data/video_generation/this_time_i_leave_s7_character_turnarounds_20261006'
SCENES = 'data/video_generation/this_time_i_leave_s7_fixed_scene_sample_20261006'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def local(path, root=ROOT):
    path = Path(path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'Source outside project: {path}')
    return path


def identity(path, expected=None):
    result = {'path':str(path), 'expected_sha256':expected, 'exists':path.is_file()}
    if path.is_file():
        result.update(bytes=path.stat().st_size, observed_sha256=sha(path))
        if expected is None:
            result['expected_sha256'] = result['observed_sha256']
        result['integrity'] = 'ok' if result['observed_sha256'] == result['expected_sha256'] else 'hash_mismatch'
    else:
        result.update(bytes=None, observed_sha256=None, integrity='missing')
    return result

def image_mime(path):
    if not path.is_file():
        return None
    with path.open('rb') as file:
        header=file.read(16)
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if header.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if header.startswith(b'RIFF') and header[8:12]==b'WEBP':
        return 'image/webp'
    return 'application/octet-stream'


def import_path(value, root):
    if not isinstance(value, str) or not value or '://' in value or value.startswith(('//', '\\\\')):
        raise ValueError('Import requires a local project file path')
    path = Path(value)
    return local(path if path.is_absolute() else root / path, root)


def import_identity(value, root):
    if not isinstance(value, dict) or not re.fullmatch(r'[0-9a-fA-F]{64}', str(value.get('sha256', ''))):
        raise ValueError('Import file requires path and SHA256')
    path = import_path(value.get('path'), root)
    row = identity(path, value['sha256'].lower())
    if row['integrity'] != 'ok':
        raise ValueError(f'Import file {row["integrity"]}: {path}')
    return path, row['expected_sha256']


def collect_imports(root, evidence_file, add):
    """Append immutable, explicitly sourced images; never promotes media approval."""
    folder = root / 'data/visual_asset_library/personal_catalog_v1/imports'
    versions = set()
    for manifest_path in sorted(folder.glob('*.json')):
        manifest_path = local(manifest_path, root)
        manifest = load(manifest_path)
        if manifest.get('schema') != 'personal_local_asset_import/v1' or not isinstance(manifest.get('assets'), list) or not manifest['assets']:
            raise ValueError(f'Invalid import manifest: {manifest_path}')
        manifest_ref = evidence_file(manifest_path)
        for a in manifest['assets']:
            if not isinstance(a, dict):
                raise ValueError('Import asset must be an object')
            for key in ['asset_id', 'name', 'series_id', 'version']:
                if not isinstance(a.get(key), str) or not a[key].strip():
                    raise ValueError(f'Import asset missing {key}')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', a['asset_id']):
                raise ValueError('Import asset_id must be a stable ASCII identifier')
            if a.get('kind') not in {'character', 'scene', 'composition', 'prop', 'costume'} or a.get('style') not in {'photoreal', '3d_soft_doll'}:
                raise ValueError('Unsupported import image kind or style')
            version_key = (a['series_id'], a['version'])
            if version_key in versions:
                raise ValueError(f'Duplicate imported series/version: {version_key}')
            versions.add(version_key)
            if 'user_media_approval' not in a or a['user_media_approval'] is not None or a.get('human_identity_approval') is not None:
                raise ValueError('New imports must retain null user media and identity approval')
            selection = a.get('selection')
            if not isinstance(selection, dict) or selection.get('status') not in {'assistant_selected', 'unselected'} or not isinstance(selection.get('scope'), str) or not selection['scope'].strip():
                raise ValueError('Import requires an explicit selection status and scope')
            image, expected = import_identity(a.get('image'), root)
            mime = image_mime(image)
            if mime not in {'image/png', 'image/jpeg', 'image/webp'} or mimetypes.guess_type(str(image))[0] != mime:
                raise ValueError(f'Import image MIME/extension mismatch: {image}')
            source = a.get('source')
            if not isinstance(source, dict):
                raise ValueError('Import requires source receipt or evidence')
            sources = source.get('evidence', [])
            if not isinstance(sources, list):
                raise ValueError('Source evidence must be a list')
            sources = list(sources)
            if 'receipt' in source:
                sources.append(source['receipt'])
            if not sources:
                raise ValueError('Import requires nonempty source receipt or evidence')
            refs = []
            for ref in sources:
                path, digest = import_identity(ref, root)
                refs.append(evidence_file(path, digest))
            add(a['asset_id'], a['name'], a['kind'], a['series_id'], a['version'], a['style'],
                image, expected, manifest_ref,
                {'import_details': a.get('details', {}), 'selection': selection, 'source_service': source.get('service'),
                 'selection_is_not_user_identity_or_video_approval': True},
                {'historical_decision': None, 'human_identity_approval': None, 'user_media_approval': None,
                 'scope': 'New local image import only; selection is not media approval'}, refs)


def collect(root=ROOT):
    assets, evidence = [], {}
    def evidence_file(path, expected=None):
        path = local(path, root)
        key = str(path)
        row = identity(path, expected)
        if key in evidence and evidence[key]['expected_sha256'] != row['expected_sha256']:
            raise ValueError(f'Conflicting expected evidence identity: {key}')
        evidence[key] = row
        return key
    def add(asset_id, name, kind, series, version, style, image, expected, manifest, details, history, refs):
        image = local(image, root)
        assets.append({'asset_id':asset_id, 'name':name, 'kind':kind, 'series_id':series,
            'version':version, 'style':style, 'image':identity(image, expected),
            'mime':image_mime(image), 'extension_mime':mimetypes.guess_type(str(image))[0], 'source_manifest':manifest,
            'details':details, 'historical_review':history, 'evidence_paths':refs,
            'current_casting':{'status':'unbound', 'project_role':None, 'selected_asset_hash':None},
            'current_media_approval':None, 'api_native_eligibility':None})
    legacy_path = root / LEGACY
    legacy = load(legacy_path)
    manifest = evidence_file(legacy_path)
    for a in legacy['assets']:
        review_path = local(a['review']['path'], root)
        review = load(review_path) if review_path.is_file() else {}
        refs = [evidence_file(review_path,a['review']['sha256']),
                evidence_file(Path(a['receipt']['path']),a['receipt']['sha256'])]
        historical = {'historical_decision':a['decision'],
            'review_original':{k:review.get(k) for k in ['schema','decision','review_method','reviewed_at','video_eligible']},
            'scope':a['reuse_conditions'], 'approval_not_promoted_to_human':True}
        add('legacy.photoreal.v3.'+a['reuse_key'],a['canonical_name'],a['kind'],
            'legacy_photoreal_20260926','v3','photoreal',Path(a['image']['path']),
            a['image']['sha256'],manifest,{'reuse_key':a['reuse_key'],'aliases':a['aliases'],'tags':a['tags']},historical,refs)
    board_root = root / BOARDS
    board_manifest = board_root / 'LATEST_CHARACTER_SAMPLES.json'
    latest = load(board_manifest)
    manifest = evidence_file(board_manifest)
    note = evidence_file(board_root/'round_01/REVIEW.md')
    for code,a in latest['characters'].items():
        receipt_path, approval_path = local(a['receipt'],root), local(a['approval'],root)
        receipt, approval = load(receipt_path), load(approval_path)
        approved = approval.get('approved_characters',{}).get(code,{})
        if approved.get('sha256') != a['sha256'] or Path(approved['image']).resolve() != Path(a['image']).resolve():
            raise ValueError(f'Board confirmation identity mismatch: {code}')
        refs = [evidence_file(receipt_path),evidence_file(approval_path),note]
        historical = {'latest_sample_original':{'human_identity_approval':a.get('human_identity_approval')},
            'generation_receipt_original':{k:receipt.get(k) for k in ['schema','outcome','content_status','human_identity_approval','creative_quality_passed']},
            'identity_confirmation_original':{k:approval.get(k) for k in ['schema','source','user_text','context','scope','human_identity_and_clothing_approval','formal_start_frame_approval','video_content_approval','full_film_quality_approval']},
            'confirmation_asset_human_identity_approval':approved.get('human_identity_approval')}
        names = {'C01':'方澄','C02':'林屿'}
        clothing = {'C01':'黑色齐肩中分直发；灰蓝薄针织开衫、白色圆领T恤、深灰直筒裤',
                    'C02':'深栗短碎发稍长刘海；米驼棉衬衫卷袖、深藏蓝休闲裤'}
        add('nativeboard.photoreal.20261006.r1.'+code,names[code],'character',
            'nativeboard_20261006_'+code,'round_01','photoreal',Path(a['image']),a['sha256'],manifest,
            {'source_character_id':code,'angle':'three-view plus face board','appearance_clothing_original_description':clothing[code],
             'description_source':note,'same_name_legacy_assets_are_distinct':True},historical,refs)
    scene_root = root / SCENES
    scene_manifest = scene_root/'CURRENT_SCENE_SAMPLES.json'
    scenes = load(scene_manifest)
    manifest = evidence_file(scene_manifest)
    for code,name,version in [('office','办公室','round_03'),('corridor','走廊','corridor_round_01')]:
        a=scenes[code]
        approval_path=local(a['approval'],root)
        approval=load(approval_path)
        approved_hash=approval.get('image_sha256',approval.get('sha256'))
        if approved_hash!=a['sha256'] or Path(approval['image']).resolve()!=Path(a['image']).resolve():
            raise ValueError(f'Scene confirmation identity mismatch: {code}')
        receipt_path=Path(a.get('receipt',str(scene_root/'round_03/RECEIPT.json')))
        refs=[evidence_file(receipt_path),evidence_file(approval_path)]
        historical={'sample_manifest_original':{k:a.get(k) for k in ['human_aesthetic_approval','human_visible_layout_approval','formal_start_frame_approval']},
            'confirmation_original':{k:approval.get(k) for k in ['schema','source','user_text','question','decision','scope','next_authorized_scope','user_aesthetic_approved','user_visible_layout_approved','human_aesthetic_approval','human_visible_layout_approval','exact_physical_geometry_verified','formal_start_frame_approval','video_content_approval','full_film_quality_approval']},
            'scene_manifest_scope_original':{k:scenes[k] for k in ['exact_generated_geometry_verified','video_authorized_by_these_confirmations']}}
        add(f'scene.photoreal.20261006.{code}.{version}',name,'scene','scene_photoreal_20261006_'+code,
            version,'photoreal',Path(a['image']),a['sha256'],manifest,
            {'source_scene_id':code,'description':'已存写实审美及可见布局样板；不是精确几何或正式首帧','same_name_other_versions_remain_distinct':True},historical,refs)
    for character in ['linxiaoyu','chenmo','susu']:
        library_path = root / f'data/characters/{character}/direction_library_v1/library.json'
        library = load(library_path)
        manifest = evidence_file(library_path)
        for ref in library['references']:
            add(f'direction.3d.{character}.{library["library_version"]}.{ref["id"]}',library['character_name'],
                'character','direction_3d_'+character,library['library_version'],'3d_soft_doll',
                library_path.parent/ref['file'],None,manifest,
                {'reference_original':ref,'identity_invariants_original':library['identity_invariants'],
                 'selection_policy_original':library['selection_policy']},
                {'historical_decision':None,'human_approval':None,'scope':'Direction library description only; no approval record supplied'},[])
    collect_imports(root, evidence_file, add)
    if len({a['asset_id'] for a in assets}) != len(assets):
        raise ValueError('Duplicate stable asset IDs')
    return {'schema':'personal_local_asset_catalog/v1','created_at':now(),'assets':assets,
        'evidence_files':list(evidence.values()),'policy':{'discovery_only':True,'source_files_modified':False,
        'auto_accept_changed_sources':False,'new_production_bindings':0,'new_media_calls':0}}


def verify_catalog(catalog):
    issues = []
    for kind, rows in [('image',[(a['asset_id'],a['image']) for a in catalog['assets']]),
                       ('evidence',[(r['path'],r) for r in catalog['evidence_files']])]:
        for key,row in rows:
            actual = identity(Path(row['path']),row['expected_sha256'])
            if actual['integrity'] != 'ok' or actual.get('bytes') != row.get('bytes'):
                issues.append({'kind':kind,'id':key,'expected':row,'actual':actual})
    return {'at':now(),'status':'ok' if not issues else 'needs_attention','issues':issues,
        'asset_count':len(catalog['assets']),'content_review_performed':False}


def render(catalog, output, report):
    esc = html.escape
    def link(path):
        path = local(path)
        return quote(os.path.relpath(path,output).replace('\\','/'),safe='/._-')
    issues = {i['id']:i['actual']['integrity'] for i in report['issues'] if i['kind']=='image'}
    bad_evidence = {i['id'] for i in report['issues'] if i['kind']=='evidence'}
    cards = []
    for a in catalog['assets']:
        status = issues.get(a['asset_id'],'ok')
        if status=='ok' and bad_evidence.intersection([a['source_manifest']]+a['evidence_paths']):
            status='evidence_missing_or_hash_mismatch'
        labels = {'character':'人物','scene':'场景','composition':'构图','prop':'道具','costume':'服装','photoreal':'写实','3d_soft_doll':'3D软偶'}
        title = f'{a["name"]} · {labels[a["style"]]} · {a["version"]}'
        search = ' '.join([title,a['asset_id'],a['series_id'],json.dumps(a['details'],ensure_ascii=False)]).lower()
        src = link(a['image']['path'])
        preview = f'<a href="{src}"><img loading="lazy" src="{src}" alt="{esc(title,quote=True)}"></a>' if status=='ok' else '<p class="bad">原图缺失或hash不符，预览暂停</p>'
        evidence = ' · '.join(f'<a href="{link(p)}">证据{n+1}</a>' for n,p in enumerate([a['source_manifest']]+a['evidence_paths']))
        history = json.dumps(a['historical_review'],ensure_ascii=False,indent=2)
        cards.append(f'<article data-search="{esc(search,quote=True)}" data-style="{a["style"]}" data-kind="{a["kind"]}">{preview}<h2>{esc(title)}</h2><p>{labels[a["kind"]]} · 完整性：{esc(status)} · 本片角色：未绑定</p><code>{esc(a["asset_id"])}</code><p>SHA256：{esc(a["image"]["expected_sha256"] or "未知")}</p><details><summary>原描述与历史范围</summary><pre>{esc(json.dumps(a["details"],ensure_ascii=False,indent=2))}</pre><pre>{esc(history)}</pre></details><p>{evidence}</p></article>')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>个人资产库</title><style>body{font:15px system-ui;background:#f2f4f7;margin:24px;color:#18212d}header{max-width:1100px;margin:auto}input,select{font:inherit;padding:10px;margin:5px}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;margin-top:20px}article{background:white;padding:16px;border-radius:12px;overflow-wrap:anywhere}img{width:100%;height:250px;object-fit:contain;background:#e9edf2}h2{font-size:18px}pre{white-space:pre-wrap;font-size:12px}code{font-size:12px}.bad{color:#a11}p{line-height:1.6}[hidden]{display:none!important}</style><header><h1>项目自有资产库</h1><p>只读检索与准备；历史状态按原来源保留。入库不代表本片选角、接口资格或视频批准。同名不同风格/服装保持独立版本。</p><input id="q" placeholder="搜索姓名、资产ID、角度、服装"><select id="style"><option value="">所有风格</option><option value="photoreal">写实</option><option value="3d_soft_doll">3D软偶</option></select><select id="kind"><option value="">所有类别</option><option value="character">人物</option><option value="scene">场景</option><option value="composition">构图</option><option value="prop">道具</option><option value="costume">服装</option></select><span id="count"></span><p>完整性为最近一次 build/verify 的文件hash结果，不是内容审核。源变化先报告，原期望hash保留。</p>'''+f'<p>检查状态：{esc(report["status"])}；异常 {len(report["issues"])} 项</p></header><main>'+''.join(cards)+'''</main><script>const cards=[...document.querySelectorAll('article')];function filter(){const q=document.querySelector('#q').value.toLowerCase(),s=document.querySelector('#style').value,k=document.querySelector('#kind').value;let n=0;for(const a of cards){a.hidden=!!((q&&!a.dataset.search.includes(q))||(s&&a.dataset.style!==s)||(k&&a.dataset.kind!==k));if(!a.hidden)n++}document.querySelector('#count').textContent=n+' 项'}for(const id of ['q','style','kind'])document.getElementById(id).addEventListener('input',filter);filter();</script></html>'''


def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def record(output,event):
    with (output/'EVENTS.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'at':now(),**event},ensure_ascii=False)+'\n')


def build(root=ROOT, output=OUT):
    output.mkdir(parents=True,exist_ok=True)
    previous = output/'CATALOG.json'
    if previous.exists():
        old = load(previous)
        report = verify_catalog(old)
        if report['issues']:
            write_json(output/'VERIFY_LATEST.json',report)
            (output/'INDEX.html').write_text(render(old,output,report),encoding='utf-8')
            record(output,{'event':'build_refused_source_change','issue_count':len(report['issues'])})
            return report
    try:
        candidate = collect(root)
    except (ValueError, KeyError, TypeError, OSError) as error:
        report = {'at':now(), 'status':'needs_attention', 'issues':[{'kind':'import_validation', 'error':str(error)}],
                  'content_review_performed':False}
        write_json(output/'VERIFY_LATEST.json',report)
        record(output,{'event':'import_refused', 'error':str(error)})
        return report
    if previous.exists():
        # Keep first-import identities even if a source changes between checks.
        old_images={a['asset_id']:a['image'] for a in old['assets']}
        old_evidence={r['path']:r for r in old['evidence_files']}
        for asset in candidate['assets']:
            if asset['asset_id'] in old_images:
                asset['image']=old_images[asset['asset_id']]
        for index,row in enumerate(candidate['evidence_files']):
            if row['path'] in old_evidence:
                candidate['evidence_files'][index]=old_evidence[row['path']]
    report = verify_catalog(candidate)
    if report['issues']:
        write_json(output/'VERIFY_LATEST.json',report)
        record(output,{'event':'initial_import_refused','issue_count':len(report['issues'])})
        return report
    if previous.exists():
        folder=output/'snapshots'
        folder.mkdir(exist_ok=True)
        stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        shutil.copyfile(previous,folder/f'CATALOG_{stamp}_{sha(previous)[:12]}.json')
        candidate['created_at']=old['created_at']
    candidate['last_built_at']=now()
    write_json(previous,candidate)
    write_json(output/'VERIFY_LATEST.json',report)
    (output/'INDEX.html').write_text(render(candidate,output,report),encoding='utf-8')
    record(output,{'event':'build_completed','assets':len(candidate['assets']),'catalog_sha256':sha(previous)})
    return report


def main():
    parser=argparse.ArgumentParser(description='本地个人资产检索：不上传、不生成、不修改旧库')
    parser.add_argument('command',choices=['build','list','verify'])
    parser.add_argument('--query',default='')
    parser.add_argument('--style',choices=['photoreal','3d_soft_doll'])
    args=parser.parse_args()
    if args.command=='build':
        result=build()
    elif args.command=='verify':
        catalog=load(OUT/'CATALOG.json')
        result=verify_catalog(catalog)
        write_json(OUT/'VERIFY_LATEST.json',result)
        (OUT/'INDEX.html').write_text(render(catalog,OUT,result),encoding='utf-8')
        record(OUT,{'event':'verify_completed','status':result['status'],'issues':len(result['issues'])})
    else:
        assets=load(OUT/'CATALOG.json')['assets']
        result=[{'id':a['asset_id'],'name':a['name'],'style':a['style'],'version':a['version'],'path':a['image']['path'],'current_casting':'unbound'} for a in assets if (not args.style or a['style']==args.style) and args.query.lower() in json.dumps(a,ensure_ascii=False).lower()]
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return int(isinstance(result,dict) and result.get('status')!='ok')


if __name__=='__main__':
    raise SystemExit(main())
