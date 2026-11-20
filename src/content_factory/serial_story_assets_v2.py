"""Append-only, book-scoped image versions and verified shot bindings."""
from pathlib import Path
import hashlib
import shutil
import uuid
from PIL import Image
from .corpus_screenplay_v1 import read, freeze, digest
from .serial_story_runtime_v2 import run_lock
from .serial_story_contract_v1 import split_shots
from src.platform_adapter.fanqie_book_corpus import atomic


def register(library, image_path, *, book_id, entity_id, kind, view):
    library = Path(library).resolve(); path = Path(image_path).resolve()
    if kind not in ('character', 'place') or not all(str(x).strip() for x in (book_id,entity_id,view)):
        raise ValueError('invalid_asset_identity')
    if path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp') or not path.is_file() or path.stat().st_size>50*1024*1024:
        raise ValueError('invalid_image_file')
    with Image.open(path) as im: im.verify()
    library.mkdir(parents=True,exist_ok=True)
    with run_lock(library):
        index = read(library/'INDEX.json') if (library/'INDEX.json').exists() else {'assets':[]}
        previous = [a for a in index['assets'] if (a['book_id'],a['entity_id'],a['kind'],a['view'])==(str(book_id),entity_id,kind,view)]
        asset_id = previous[0]['asset_id'] if previous else uuid.uuid4().hex
        version = len(previous)+1
        dest = library/f'{asset_id}_v{version}{path.suffix.lower()}'
        with path.open('rb') as src, dest.open('xb') as dst: shutil.copyfileobj(src,dst)
        row = {'asset_id':asset_id,'version':version,'book_id':str(book_id),'entity_id':entity_id,
               'kind':kind,'view':view,'file':dest.name,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}
        freeze(library/f'{asset_id}_v{version}.json',row)
        index['assets'].append(row); atomic(library/'INDEX.json',index)
        return row


def bind(library, book_id, bound, shots, selections):
    library = Path(library).resolve()
    index = read(library/'INDEX.json')
    if not shots or digest(split_shots(bound,max(s['end']-s['start'] for s in shots)))!=digest(shots):
        raise ValueError('shot_candidate_mismatch')
    chosen=[]
    for item in selections:
        rows=[a for a in index['assets'] if a['asset_id']==item['asset_id'] and a['version']==item['version']]
        if len(rows)!=1: raise ValueError('asset_version_missing')
        row=rows[0]; path=(library/row['file']).resolve()
        if not path.is_relative_to(library) or row['book_id']!=str(book_id): raise ValueError('asset_scope_mismatch')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']: raise ValueError('asset_changed')
        chosen.append(row)
    if len({(a['asset_id'],a['version']) for a in chosen})!=len(chosen): raise ValueError('duplicate_asset_selection')
    if len({(a['kind'],a['entity_id'],a['view']) for a in chosen})!=len(chosen): raise ValueError('conflicting_asset_versions')
    by_scene={s['id']:s for s in bound['script']['scenes']}
    result=[]
    for shot in shots:
        scene=by_scene[shot['scene_id']]
        needed={('character',p) for p in scene['cast']}|{('place',scene['place_id'])}
        rows=[a for a in chosen if (a['kind'],a['entity_id']) in needed]
        if {(a['kind'],a['entity_id']) for a in rows}!=needed: raise ValueError('shot_assets_incomplete')
        result.append({**shot,'assets':rows})
    return {'book_id':str(book_id),'candidate_sha256':digest(bound),'asset_selection_sha256':digest(chosen),
            'shots':result,'media_generated':False}
