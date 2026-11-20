"""Review ownership constrained by the actual stage, not a global enum."""
from copy import deepcopy
from jsonschema import validate
from .serial_story_contract_v4 import *


def review_owners(name):
    if name.startswith('MATERIAL_REVIEW_'): return ['materials']
    if name.startswith('BIBLE_REVIEW_'): return ['materials','bible']
    if name=='OUTLINE_REVIEW': return ['materials','bible','outline']
    if name.startswith(('EPISODE_REVIEW_','FINAL_CONTENT_','FINAL_TIMING_')):
        return ['materials','bible','outline','episode','staging']
    raise ValueError('unknown_review_stage')


def review_schema(name):
    schema=deepcopy(REVIEW)
    schema['properties']['issues']['items']['properties']['owner']={'type':'string','enum':review_owners(name)}
    return schema


def review_valid_for_stage(raw,candidate,source,name):
    validate(raw,review_schema(name))
    return review_valid(raw,candidate,source)
