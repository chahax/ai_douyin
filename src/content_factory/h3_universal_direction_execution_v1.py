"""Source-recomputed directing policy over two isolated, proven H3 transports.

The library transport supports scene changes and adult/voiceover material. The
asset-flow transport adds typed actor/contact continuity for same-scene clips.
Neither shared module nor any completed run is changed by this adapter.
"""
from copy import deepcopy
import importlib.util
from pathlib import Path
import types

from . import h3_asset_flow_v2 as flow
from . import h3_asset_flow_execution_v1 as transport
from . import h3_contact_prompt_v1 as contacts
from . import h3_active_contact_v1 as contact_state
from . import visual_h3_library_continuation_v1 as library
from . import video_directing_policy_v1 as direction

VERSION = 'h3_universal_direction_execution/v1'


def _same(bound, value):
    if Path(value).resolve() != bound:
        raise ValueError('universal_executor_bound_to_one_run')


def _prompt_only(before_m, before_g, after):
    restored = deepcopy(after['graph'])
    restored['condition']['inputs']['prompt'] = before_g['condition']['inputs']['prompt']
    allowed = {'compiled_prompt', 'compiled_prompt_utf8_sha256', 'graph_sha256', 'directing_policy'}
    if (restored != before_g or set(after['manifest']) != set(before_m) | {'directing_policy'}
            or any(after['manifest'][k] != v for k, v in before_m.items() if k not in allowed)):
        raise ValueError('directing_policy_cannot_change_source_assets_state_or_graph')


def asset_for_run(run, policy_binding):
    """Frozen asset transport with optional source-bound contact and directions."""
    bound = Path(run).resolve()
    name = 'src.content_factory._h3_universal_asset_' + flow.core.sha(str(bound))[:12]
    spec = importlib.util.spec_from_file_location(name, transport.__file__)
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    original_derive, original_codes, original_load = api._derive, api._codes, api._load

    def derive(out, value, profiles):
        _same(bound, value)
        manifest, graph, entry, scope = original_derive(out, value, profiles)
        source_spec = flow._bound(manifest['spec'])
        if 'contact_plan' in source_spec:
            result = contacts.apply(manifest, graph)
            restored = deepcopy(result['graph'])
            restored['condition']['inputs']['prompt'] = graph['condition']['inputs']['prompt']
            if restored != graph:
                raise ValueError('contact_must_preserve_nonprompt_graph')
            manifest, graph = result['manifest'], result['graph']
        result = direction.apply(manifest, graph, policy_binding)
        _prompt_only(manifest, graph, result)
        return result['manifest'], result['graph'], entry, scope

    def codes(profiles, extra):
        values = original_codes(profiles, extra)
        for path in (__file__, direction.__file__, contacts.__file__, contact_state.__file__):
            binding = flow.bind(path)
            if binding not in values:
                values.append(binding)
        return values

    def load(value, *, current=True):
        _same(bound, value)
        return original_load(value, current=current)

    api._derive, api._codes, api._load = derive, codes, load
    for name in ('prepare', 'submit', 'collect_known', 'status', 'launch_request'):
        original = getattr(api, name)
        def guard(value, *args, _original=original, **kwargs):
            _same(bound, value)
            return _original(value, *args, **kwargs)
        setattr(api, name, guard)
    return api


def _replace_closure(function, replacements):
    """Replace only private factory cells, without touching shared globals."""
    def cell(value):
        return (lambda: value).__closure__[0]
    actual = dict(zip(function.__code__.co_freevars, function.__closure__ or ()))
    if not set(replacements) <= set(actual):
        raise ValueError('private_factory_closure_contract_changed')
    cells = tuple(cell(replacements[k]) if k in replacements else actual[k]
                  for k in function.__code__.co_freevars)
    clone = types.FunctionType(function.__code__, function.__globals__, function.__name__,
                               function.__defaults__, cells)
    clone.__kwdefaults__ = function.__kwdefaults__
    return clone


def library_for_run(series, policy_binding):
    """Directions before graph compilation, including independent scene Guide0."""
    bound = Path(series).resolve()
    api = library.for_run(bound)
    original_input = api.input_value
    original_validate = api.validate_input
    original_prepare = api.prepare_video
    original_approval = api._approval
    namespace = original_validate.__globals__
    if namespace is library.base.__dict__:
        raise ValueError('private_library_namespace_required')

    def input_value(value, sid):
        _same(bound, value)
        result = original_input(value, sid)
        if 'status' in result:
            return result
        fake = {'condition': {'inputs': {'prompt': result['compiled_prompt']}}}
        guide_review = flow._bound(result['guide_review'])
        manifest = deepcopy(result)
        manifest.update(graph_sha256=flow.digest(fake), guide={'review': guide_review})
        transformed = direction.apply(manifest, fake, policy_binding)
        _prompt_only(manifest, fake, transformed)
        result = deepcopy(result)
        for key in ('compiled_prompt', 'compiled_prompt_utf8_sha256', 'directing_policy'):
            result[key] = transformed['manifest'][key]
        return result

    def validate_input(binding):
        result = original_validate(binding)
        receipt = result.get('directing_policy')
        if not isinstance(receipt, dict) or receipt.get('policy_binding') != policy_binding:
            raise ValueError('pinned_universal_direction_receipt_required')
        result['proof']['directing_policy'] = deepcopy(receipt)
        return result

    compiled_prepare = _replace_closure(original_prepare, {'input_value': input_value})

    def prepare_video(value, sid, *, code_files=()):
        _same(bound, value)
        return compiled_prepare(value, sid, code_files=tuple(code_files) + (__file__, direction.__file__))

    def approval(value, sid):
        _same(bound, value)
        original_approval(value, sid)
        record = flow.read(api.part(bound, sid)/'ROOT_LAUNCH_VIDEO.json')
        if str(record.get('approved_by', '')).strip().lower() != 'root':
            raise ValueError('complete_Root_launch_approval_required')

    namespace.update(input_value=input_value, validate_input=validate_input, prepare_video=prepare_video,
                     _approval=approval)
    api.input_value, api.validate_input, api.prepare_video = input_value, validate_input, prepare_video
    api._approval = approval
    for name in ('submit', 'collect_known', 'status', 'launch_request', 'review_request'):
        original = getattr(api, name)
        def guard(value, *args, _original=original, **kwargs):
            _same(bound, value)
            return _original(value, *args, **kwargs)
        setattr(api, name, guard)
    return api
