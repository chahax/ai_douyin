from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from src.content_factory.novel_adaptation.schema_projection import compact_enums


def test_factoring_preserves_all_enum_choices_and_rejects_the_same_invalid_values():
    e={'type':'string','enum':['source-'+str(n) for n in range(120)]}
    original={'type':'object','properties':{'a':e,'b':e},'required':['a','b'],'additionalProperties':False}
    old=deepcopy(original);result=compact_enums(original)
    assert original==old and len(json.dumps(result))<len(json.dumps(original))
    for n in range(120):
        value={'a':'source-'+str(n),'b':'source-'+str(119-n)}
        assert Draft202012Validator(original).is_valid(value)==Draft202012Validator(result).is_valid(value)==True
    for value in ({'a':'missing','b':'source-1'},{'a':1,'b':'source-1'},{'a':'source-1'}):
        assert not Draft202012Validator(original).is_valid(value) and not Draft202012Validator(result).is_valid(value)


def test_existing_refs_and_defs_keep_their_meaning():
    e={'type':'string','enum':['long-source-'+str(n) for n in range(80)]}
    original={'$defs':{'old':{'type':'array','items':e}},'type':'object','properties':{'a':{'$ref':'#/$defs/old'},'b':e},'required':['a','b']}
    result=compact_enums(original)
    for value in ({'a':['long-source-1'],'b':'long-source-2'},{'a':['bad'],'b':'long-source-2'}):
        assert Draft202012Validator(original).is_valid(value)==Draft202012Validator(result).is_valid(value)
