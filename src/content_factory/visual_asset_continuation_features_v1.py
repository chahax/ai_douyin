"""Source-bound continuation cards without guessing absent visual traits.

The sealed first-minute feature-card implementation stays unchanged. Its
immutable binding builder is reused in a private function namespace; only
character-description extraction is extended for the newly selected siblings.
"""
from copy import deepcopy
from types import FunctionType

from . import visual_asset_feature_cards_v1 as base

FEATURE_TERMS = deepcopy(base.FEATURE_TERMS)
FEATURE_TERMS.update({
    'ye_dong': {
        'face': 'rather angular oval face',
        'hair': 'short rough black hair with a slightly exposed forehead',
        'eyes': None,
        'build': 'slim small build',
        'expression': 'serious protective expression',
        'wardrobe': 'Faded dusty blue oversized cotton short-sleeve shirt, old charcoal trousers, worn dark canvas shoes.'},
    'ye_yaner': {
        'face': 'delicate round-oval face',
        'hair': 'neatly tied small pigtails',
        'eyes': 'bright dark eyes',
        'build': 'petite natural child build',
        'expression': 'gently attentive expression',
        'wardrobe': 'Simple faded pale small-floral long-enough cotton dress, white ankle socks and old plain black Mary Jane shoes.'}
})


def _character_description(row, cast_plan, cast_binding, terms):
    eid = row['entity_id']
    if eid in base.FEATURE_TERMS:
        # Preserve the first-minute three actors' exact existing descriptions.
        if terms.get(eid) != base.FEATURE_TERMS[eid]:
            raise ValueError('existing_character_feature_terms_must_not_change')
        return base._character_description(row, cast_plan, cast_binding, terms)
    if eid not in ('ye_dong', 'ye_yaner'):
        raise ValueError('explicit_continuation_character_required')
    matches = [d for d in cast_plan.get('characters', []) if d.get('id') == eid]
    if len(matches) != 1:
        raise ValueError('character_design_description_missing')
    design, features = matches[0], terms.get(eid)
    if (not isinstance(features, dict)
            or set(features) != {'face', 'hair', 'eyes', 'build', 'expression', 'wardrobe'}
            or any(not isinstance(features.get(k), str) or not features[k].strip()
                   for k in ('face', 'hair', 'build', 'wardrobe'))
            or any(features.get(k) is not None
                   and (not isinstance(features[k], str) or not features[k].strip())
                   for k in ('eyes', 'expression'))):
        raise ValueError('source_supported_character_features_required')
    prompt = design.get('front_prompt', '')
    if any(v not in prompt for v in features.values() if v is not None):
        raise ValueError('features_not_exact_design_evidence')
    provenance = row.get('provenance', {})
    manifest_path = provenance.get('manifest_path')
    if not manifest_path or base.bind(manifest_path)['sha256'] != provenance.get('manifest_sha256'):
        raise ValueError('character_generation_manifest_missing_or_changed')
    if base.read(manifest_path).get('cast_plan_sha256') != cast_binding['sha256']:
        raise ValueError('description_not_bound_to_asset_design_version')
    source = cast_plan['source']
    base.check_binding(source)
    if provenance.get('source_script') != source or design.get('identity_group') != row['identity_group']:
        raise ValueError('character_description_family_mismatch')
    ordered = ('face', 'hair', 'eyes', 'build', 'expression', 'wardrobe')
    description = '; '.join(features[k] for k in ordered if features[k] is not None)
    return dict(name=design.get('name', eid), description=description,
        appearance_description=description,
        features={k: features[k] for k in ordered if k != 'wardrobe'},
        feature_status={k: 'not_specified_in_source' for k in ordered if features[k] is None},
        wardrobe=features['wardrobe'],
        age={k: deepcopy(design.get(k)) for k in ('fact_age', 'visual_design_age',
                    'age_evidence', 'visual_design_is_not_novel_fact')},
        description_kind='source_bound_visual_design_not_image_identity_certification',
        source=dict(cast_plan=cast_binding, source_script=source,
                    generation_manifest=base.bind(manifest_path), source_facts=deepcopy(design.get('source_facts')),
                    feature_prompt_spans={k: dict(start=prompt.index(v), end=prompt.index(v)+len(v), text=v)
                                          for k, v in features.items() if v is not None}),
        reference_photo_setup_is_not_video_instruction=True)


# Keep the original builder's registry lookup, immutable output and notices.
_namespace = dict(base.__dict__)
_namespace['_character_description'] = _character_description
_builder = FunctionType(base.prepare_binding.__code__, _namespace,
    name='prepare_continuation_binding', argdefs=base.prepare_binding.__defaults__,
    closure=base.prepare_binding.__closure__)
_builder.__kwdefaults__ = base.prepare_binding.__kwdefaults__


def prepare_binding(output_dir, *, library, book_id, cast_plan, selection, feature_terms=None):
    return _builder(output_dir, library=library, book_id=book_id, cast_plan=cast_plan,
                    selection=selection, feature_terms=FEATURE_TERMS if feature_terms is None else feature_terms)
