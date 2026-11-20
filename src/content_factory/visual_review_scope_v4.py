"""Server-owned applicability, never a provider's permission to skip checks."""
from copy import deepcopy

CHARACTER_CHECKS=('identity','view','clothing','anatomy')
DETAIL_REQUIRED={
    'face':('identity','view','anatomy'),
    'clothing':('view','clothing','anatomy'),
    'hands':('view','anatomy'),
}
ALIASES={'face_detail':'face','clothing_detail':'clothing','hands_detail':'hands'}


def character_scope(view,*,bound_roi=False,composition=False):
    view=ALIASES.get(view,view)
    detailed=bool(bound_roi and not composition and view in DETAIL_REQUIRED)
    required=DETAIL_REQUIRED[view] if detailed else CHARACTER_CHECKS
    return dict(schema='visual_review_scope/v4',kind='character',view=view,
        required=list(required),not_applicable=[k for k in CHARACTER_CHECKS if k not in required],
        identity_basis='canonical_roi_lineage' if detailed and 'identity' not in required else 'visual_comparison',
        canonical_roi_required=detailed)


def verify_scope(value,view):
    expected=character_scope(view,bound_roi=True)
    if not isinstance(value,dict) or value!=expected or not expected['canonical_roi_required']:
        raise ValueError('invalid_detail_visual_scope')
    return deepcopy(expected)
