"""A run-bound private instance of frozen execution v1 with contact derivation.

Only the private instance's derivation and code ledger are extended. The shared
v1 module, submission/unknown protection, staging and known-ID collection stay
unchanged. There is no caller-supplied prompt or live global monkeypatch.
"""
from copy import deepcopy
import importlib.util
from pathlib import Path

from . import h3_asset_flow_v2 as flow
from . import h3_asset_flow_execution_v1 as transport
from . import h3_contact_prompt_v1 as presentation
from . import h3_active_contact_v1 as contact


def for_run(run):
    bound=Path(run).resolve()
    name='src.content_factory._h3_contact_execution_private_'+flow.core.sha(str(bound))[:12]
    spec=importlib.util.spec_from_file_location(name,transport.__file__)
    private=importlib.util.module_from_spec(spec);spec.loader.exec_module(private)
    original_derive,original_codes,original_load=private._derive,private._codes,private._load
    def same(value):
        if Path(value).resolve()!=bound:raise ValueError('contact_executor_bound_to_one_run')
    def derive(out,value,profiles):
        same(value)
        manifest,graph,entry,scope=original_derive(out,value,profiles)
        result=presentation.apply(manifest,graph)
        changed=deepcopy(result['graph']);changed['condition']['inputs']['prompt']=graph['condition']['inputs']['prompt']
        allowed={'compiled_prompt','compiled_prompt_utf8_sha256','graph_sha256','contact_continuity'}
        if (flow.digest(changed)!=flow.digest(graph)
                or set(result['manifest'])!=set(manifest)|{'contact_continuity'}
                or any(flow.digest(result['manifest'][k])!=flow.digest(v) for k,v in manifest.items() if k not in allowed)):
            raise ValueError('contact_presentation_can_only_extend_verified_prompt')
        return result['manifest'],result['graph'],entry,scope
    def codes(profiles,extra):
        values=original_codes(profiles,extra)
        for p in (__file__,presentation.__file__,contact.__file__):
            b=flow.bind(p)
            if b not in values:values.append(b)
        return values
    def load(value,*,current=True):
        same(value)
        return original_load(value,current=current)
    private._derive=derive;private._codes=codes;private._load=load
    # Guard before the original functions mkdir or acquire any directory lock.
    for name in ('prepare','submit','collect_known','status','launch_request'):
        original=getattr(private,name)
        def guarded(run,*args,_call=original,**kwargs):
            same(run)
            return _call(run,*args,**kwargs)
        setattr(private,name,guarded)
    return private
