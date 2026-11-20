"""Version-pinned library assets and source-bound feature cards for video packets.

This module never generates images, mutates the registry, or dispatches media.
Features describe identity/wardrobe, separately from a reference photo's pose.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import visual_asset_registry_v3 as registry

CARD_SCHEMA = 'visual_asset_feature_card/v1'
BINDING_SCHEMA = 'visual_library_binding_index/v1'
APPROVAL_SCHEMA = 'visual_library_binding_approval/v1'
BOOK_ID = '7302660145530539062'

DEFAULT_SELECTION = {
    'characters': {
        'su_mo': {'front': {'asset_id': 'f44d5ba27f24dabaf7f5d2ac5134b04f', 'version': 1},
                  'left_oblique': {'asset_id': '7b53dc5e51b4b75ffb4ec4485428287a', 'version': 1},
                  'right_oblique': {'asset_id': 'f7ebe1890a9b4dee0c99d2b53ac1744e', 'version': 1}},
        'ye_nan': {'front': {'asset_id': '131fdd0b6c917c1cee40301d89958c5e', 'version': 1},
                   'left_oblique': {'asset_id': '1ed97c12f6b74d64a46f53f7408b667e', 'version': 1},
                   'right_oblique': {'asset_id': 'aba0da26544650f8356c4255c0429541', 'version': 1}},
        'ye_xijue': {'front': {'asset_id': 'c961d00790d5975b2bff11f4975fcb46', 'version': 1},
                     'left_oblique': {'asset_id': '6cfed1145d447b5e246575c6762d4286', 'version': 1},
                     'right_oblique': {'asset_id': '36b5c23eb7819a33943edf4099207405', 'version': 1}}
    },
    'places': {'su_mo_room': {
        'front': {'asset_id': '1a437fadb696efa21c6e388d1d5ca81f', 'version': 4},
        'side': {'asset_id': 'fbca884355f49003b6f9c155c477c48e', 'version': 2}}}
}

# Exact substrings from this existing CAST_PLAN, not newly inferred image facts.
FEATURE_TERMS = {
    'su_mo': {
        'face': 'ordinary long oval face with a straight nose',
        'hair': 'short slightly untidy black hair',
        'eyes': 'tired alert eyes', 'build': 'lean adult build',
        'wardrobe': 'Worn dark charcoal jacket over a faded plain light gray collared cotton shirt, dark old trousers and simple black shoes.'},
    'ye_nan': {
        'face': 'narrow oval face', 'hair': 'Short black hair with a side-swept fringe',
        'eyes': 'attentive cautious eyes', 'build': 'slender childhood build',
        'wardrobe': 'Faded brown-gray short-sleeve cotton shirt with the sleeve edges rolled up, old dark gray-green trousers, worn cloth shoes.'},
    'ye_xijue': {
        'face': 'round youthful face', 'hair': 'short straight black hair with a soft uneven fringe',
        'eyes': 'large bright healthy dark eyes', 'build': 'small slim childhood body',
        'wardrobe': 'Washed-out old beige cotton short-sleeve shirt with small frayed holes and worn seams, old gray knee-length shorts, worn plain cloth shoes.'}
}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def bind(path):
    p = Path(path).resolve()
    return {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}


def check_binding(binding):
    p = Path(binding['path']).resolve()
    if bind(p) != {'path': str(p), 'sha256': binding['sha256']}:
        raise ValueError('bound_file_changed')
    return p


def freeze(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        if read(p) != value:
            raise ValueError('immutable_binding_changed')
    else:
        p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return bind(p)


def _notice(code, entity_id=None, view=None, *, reason=None, action=None):
    return {'code': code, 'entity_id': entity_id, 'view': view,
            'reason': reason or code,
            'action': action or '补齐指定素材或描述并确认绑定后，再继续本段。'}


def _missing(notices):
    return {'status': 'missing_notice', 'notices': notices,
            'notification_required': True, 'model_dispatch_allowed': False,
            'new_model_calls': 0}


def _safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', value):
        raise ValueError('invalid_entity_id')
    return value


def _asset(library, book_id, entity_id, kind, view, selected):
    if (not isinstance(selected, dict) or not selected.get('asset_id')
            or not isinstance(selected.get('version'), int) or isinstance(selected['version'], bool)):
        raise ValueError('exact_asset_id_and_version_required')
    rows = registry.get(library, book_id=book_id, asset_id=selected['asset_id'],
                        version=selected['version'], entity_id=entity_id, kind=kind, view=view)
    if len(rows) != 1:
        raise ValueError('corresponding_library_asset_missing')
    row = rows[0]
    if row['status'] not in ('reviewed', 'candidate'):
        raise ValueError('library_asset_rejected_or_unavailable')
    image = bind(row['path'])
    if image['sha256'] != row['sha256']:
        raise ValueError('library_image_changed')
    record = bind(Path(library) / (row['asset_id'] + '_v' + str(row['version']) + '.json'))
    summary = {k: row[k] for k in ('asset_id', 'version', 'entity_id', 'kind', 'view',
                                   'design_version', 'identity_group')}
    summary.update(image=image, registry_record=record, status_at_binding=row['status'])
    return row, summary


def _character_description(row, cast_plan, cast_binding, terms):
    eid = row['entity_id']
    matches = [x for x in cast_plan.get('characters', []) if x.get('id') == eid]
    if len(matches) != 1:
        raise ValueError('character_design_description_missing')
    design = matches[0]
    prompt = design.get('front_prompt', '')
    features = terms.get(eid)
    if not features or set(features) != {'face', 'hair', 'eyes', 'build', 'wardrobe'}:
        raise ValueError('structured_character_features_missing')
    if any(not isinstance(v, str) or not v.strip() or v not in prompt for v in features.values()):
        raise ValueError('features_not_exact_design_evidence')
    provenance = row.get('provenance', {})
    manifest_path = provenance.get('manifest_path')
    if not manifest_path or bind(manifest_path)['sha256'] != provenance.get('manifest_sha256'):
        raise ValueError('character_generation_manifest_missing_or_changed')
    manifest = read(manifest_path)
    if manifest.get('cast_plan_sha256') != cast_binding['sha256']:
        raise ValueError('description_not_bound_to_asset_design_version')
    source = cast_plan['source']
    check_binding(source)
    if provenance.get('source_script') != source or design.get('identity_group') != row['identity_group']:
        raise ValueError('character_description_family_mismatch')
    description = '; '.join(features[k] for k in ('face', 'hair', 'eyes', 'build', 'wardrobe'))
    return dict(name=design.get('name', eid), description=description,
                appearance_description=description,
                features={k: features[k] for k in ('face', 'hair', 'eyes', 'build')},
                wardrobe=features['wardrobe'],
                age={k: deepcopy(design.get(k)) for k in ('fact_age', 'visual_design_age',
                        'age_evidence', 'visual_design_is_not_novel_fact')},
                description_kind='source_bound_visual_design_not_image_identity_certification',
                source=dict(cast_plan=cast_binding, source_script=source,
                            generation_manifest=bind(manifest_path), source_facts=deepcopy(design.get('source_facts'))),
                reference_photo_setup_is_not_video_instruction=True)


def _place_description(row):
    entity = row.get('provenance', {}).get('entity', {})
    description = entity.get('layout_design', '')
    layout, materials = entity.get('spatial_layout'), entity.get('static_materials')
    if not description.strip() or not isinstance(layout, dict) or not layout or not isinstance(materials, dict) or not materials:
        raise ValueError('place_description_layout_or_materials_missing')
    if entity.get('id') != row['entity_id'] or entity.get('design_version') != row['design_version']:
        raise ValueError('place_description_version_mismatch')
    return dict(name=entity.get('name', row['entity_id']), description=description,
                appearance_description=description,
                features=dict(layout=deepcopy(layout), materials=deepcopy(materials)),
                description_kind='source_bound_environment_design',
                source=dict(registry_entity=deepcopy(entity), source_script=deepcopy(row.get('provenance', {}).get('source'))))


def prepare_binding(output_dir, *, library, book_id, cast_plan, selection, feature_terms=None):
    """Create an immutable project mapping through exact registry lookups, no latest fallback."""
    output, library = Path(output_dir).resolve(), Path(library).resolve()
    notices, cards = [], {'characters': {}, 'places': {}}
    try:
        cast_binding = bind(cast_plan)
        cast = read(cast_plan)
    except (OSError, ValueError, TypeError) as error:
        return _missing([_notice('cast_design_source_unavailable', reason=str(error))])
    terms = FEATURE_TERMS if feature_terms is None else feature_terms
    if (not isinstance(selection, dict) or set(selection) != set(cards)
            or any(not isinstance(selection[k], dict) or not selection[k] for k in cards)):
        return _missing([_notice('character_and_place_selection_required')])
    for category, kind in (('characters', 'character'), ('places', 'place')):
        for eid, views in selection[category].items():
            try:
                _safe_id(eid)
                if not isinstance(views, dict) or 'front' not in views:
                    raise ValueError('front_binding_required')
                images, rows = {}, {}
                for view, chosen in views.items():
                    rows[view], images[view] = _asset(library, book_id, eid, kind, view, chosen)
                front = rows['front']
                if any(r['identity_group'] != front['identity_group'] or r['design_version'] != front['design_version'] for r in rows.values()):
                    raise ValueError('selected_views_different_identity_or_design_version')
                if len({v['image']['sha256'] for v in images.values()}) != len(images):
                    raise ValueError('multiple_views_reuse_same_pixels')
                description = (_character_description(front, cast, cast_binding, terms)
                               if kind == 'character' else _place_description(front))
                # All view generation records must belong to this same cast plan.
                if kind == 'character':
                    for row in rows.values():
                        _character_description(row, cast, cast_binding, terms)
                cards[category][eid] = dict(schema=CARD_SCHEMA, book_id=book_id,
                    entity_id=eid, kind=kind, identity_group=front['identity_group'],
                    design_version=front['design_version'], images=images,
                    **description, production_approved=False)
            except (OSError, ValueError, KeyError, TypeError) as error:
                notices.append(_notice(str(error), eid))
    if notices:
        value = _missing(notices)
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        value['notice_record'] = freeze(output / 'notices' / (digest + '.json'), value)
        return value
    index = dict(schema=BINDING_SCHEMA, book_id=book_id, library=str(library),
                 cast_plan=cast_binding, selection=deepcopy(selection),
                 characters={}, places={}, production_approved=False)
    for category, entities in cards.items():
        for eid, card in entities.items():
            cb = freeze(output / 'cards' / (eid + '.json'), card)
            index[category][eid] = dict(feature_card=cb, images=card['images'])
    ib = freeze(output / 'BINDING_INDEX.json', index)
    return dict(status='binding_prepared', binding_index=ib,
                candidate_assets=[dict(asset_id=r['asset_id'], version=r['version'], sha256=r['image']['sha256'])
                    for entities in cards.values() for c in entities.values() for r in c['images'].values()
                    if r['status_at_binding'] == 'candidate'],
                binding_confirmation_required=True, model_dispatch_allowed=False, notices=[], new_model_calls=0)


def _load_index(binding_index):
    path = check_binding(binding_index) if isinstance(binding_index, dict) else Path(binding_index).resolve()
    index = read(path)
    if index.get('schema') != BINDING_SCHEMA:
        raise ValueError('library_binding_schema_required')
    check_binding(index['cast_plan'])
    cards = {'characters': {}, 'places': {}}
    for category in cards:
        for eid, item in index[category].items():
            card = read(check_binding(item['feature_card']))
            if (card.get('schema') != CARD_SCHEMA or card.get('entity_id') != eid
                    or card.get('book_id') != index['book_id'] or card.get('images') != item['images']
                    or not card.get('description', '').strip()
                    or card.get('appearance_description') != card['description']):
                raise ValueError('feature_card_description_or_asset_binding_changed')
            for view, pinned in card['images'].items():
                check_binding(pinned['registry_record'])
                _, current = _asset(index['library'], index['book_id'], eid, card['kind'], view, pinned)
                if any(current[k] != pinned[k] for k in ('asset_id', 'version', 'entity_id', 'kind', 'view',
                          'design_version', 'identity_group', 'image', 'registry_record')):
                    raise ValueError('current_library_asset_no_longer_matches_binding')
            cards[category][eid] = card
    return path, index, cards


def resolve_segment(binding_index, *, actor_ids, place_id, angle_by_actor,
                    place_views=('front', 'side'), approval_path=None, reference_limit=8):
    """Return required real images AND feature descriptions, or an actionable notice."""
    notices = []
    try:
        path, index, cards = _load_index(binding_index)
        if (not isinstance(actor_ids, (list, tuple)) or not actor_ids or len(actor_ids) != len(set(actor_ids))
                or set(angle_by_actor) != set(actor_ids)):
            raise ValueError('whole_segment_actor_and_angle_mapping_required')
        if not isinstance(reference_limit, int) or not 1 <= reference_limit <= 9:
            raise ValueError('invalid_reference_capacity')
        if approval_path is None:
            raise ValueError('initial_project_binding_confirmation_required')
        approval_path = check_binding(approval_path) if isinstance(approval_path, dict) else Path(approval_path)
        approval = read(approval_path)
        required_entities = set(index['characters']) | set(index['places'])
        if (approval.get('schema') != APPROVAL_SCHEMA or approval.get('binding_index') != bind(path)
                or not isinstance(approval.get('approved_by'), str) or not approval['approved_by'].strip()
                or not isinstance(approval.get('evidence'), list) or not approval['evidence']
                or any(not isinstance(x, str) or not x.strip() for x in approval['evidence'])
                or set(approval.get('confirmed_entities', [])) != required_entities
                or approval.get('production_approved') is not False):
            raise ValueError('project_binding_confirmation_changed_or_missing')
        allowances = approval.get('allow_candidate_assets', [])
        if (not isinstance(allowances, list) or any(not isinstance(a, dict)
                or set(a) != {'asset_id', 'version', 'sha256'}
                or not isinstance(a.get('version'), int) or a['version'] < 1
                or not re.fullmatch(r'[0-9a-f]{64}', str(a.get('sha256', '')))
                for a in allowances)):
            raise ValueError('candidate_allowance_exact_binding_required')
        allowed = {(a['asset_id'], a['version'], a['sha256']) for a in allowances}
        refs, descriptions = [], {}
        requests = []
        for cid in actor_ids:
            if cid not in cards['characters']:
                notices.append(_notice('character_binding_missing', cid)); continue
            angle = angle_by_actor[cid]
            if angle == 'front':
                notices.append(_notice('independent_angle_view_required', cid, angle)); continue
            descriptions[cid] = cards['characters'][cid]
            requests += [(cid, 'character', view, cards['characters'][cid]) for view in ('front', angle)]
        if place_id not in cards['places']:
            notices.append(_notice('place_binding_missing', place_id))
        else:
            if not place_views or len(place_views) != len(set(place_views)):
                raise ValueError('explicit_distinct_place_views_required')
            requests += [(place_id, 'place', view, cards['places'][place_id]) for view in place_views]
        for eid, kind, view, card in requests:
            if view not in card['images']:
                notices.append(_notice('bound_view_image_missing', eid, view)); continue
            pinned = card['images'][view]
            row, _ = _asset(index['library'], index['book_id'], eid, kind, view, pinned)
            key = pinned['asset_id'], pinned['version'], pinned['image']['sha256']
            if row['status'] != 'reviewed' and key not in allowed:
                notices.append(_notice('candidate_view_not_confirmed', eid, view,
                    action='核对这张候选图与指定角色的绑定，记录本次选定确认；原素材库状态不改。')); continue
            cb = index['characters' if kind == 'character' else 'places'][eid]['feature_card']
            refs.append(dict(entity_id=eid, actor_id=eid if kind == 'character' else None,
                feature_card=cb, **{k: pinned[k] for k in ('kind', 'view', 'asset_id', 'version',
                    'design_version', 'identity_group', 'image')}))
        if len(requests) > reference_limit:
            notices.append(_notice('required_references_exceed_capacity',
                reason=f'{len(requests)} required assets exceed {reference_limit} available reference slots',
                action='拆分当前视频段或更换可承载全部必要素材的适配方式；不得静默丢图。'))
        if notices:
            return _missing(notices)
        return dict(status='ready', binding_index=bind(path), binding_approval=bind(approval_path),
            references=refs, character_descriptions=descriptions,
            environment_description=cards['places'][place_id],
            source_library=index['library'], book_id=index['book_id'],
            model_dispatch_allowed=True, production_approved=False, new_model_calls=0)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return _missing([_notice(str(error))])
