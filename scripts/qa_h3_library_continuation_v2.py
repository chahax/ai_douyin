"""Order-independent cast membership in the otherwise sealed continuation QA.

Only the metadata cast-set assertion changes. Physical reference slots, actor
bindings, source spans, guide routing and saved native evidence retain their
original strict checks. The v1 source and its running observers stay untouched.
"""
from __future__ import annotations
import argparse
import ast
import inspect
import json
from pathlib import Path
import sys
import types

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path: sys.path.insert(0, str(SCRIPTS))
import qa_h3_library_continuation as previous

SEALED_PREVIOUS_SHA = 'ce11d3776702c157d8425ebd6cf201a94a57bf0552ac95e36746fa311b09f85e'
PROJECT, IDS = previous.PROJECT, previous.IDS
read, bind, checked, require, freeze, digest = previous.read, previous.bind, previous.checked, previous.require, previous.freeze, previous.digest


def same_unique_cast(actual, expected):
    """A physical cast is a unique ID set, not the source author's list order."""
    for value in (actual, expected):
        if (not isinstance(value, (list, tuple)) or not value
                or any(not isinstance(cid, str) or not cid.strip() for cid in value)
                or len(set(value)) != len(value)):
            return False
    return set(actual) == set(expected)


def _private_namespace():
    require(previous.sha(Path(previous.__file__)) == SEALED_PREVIOUS_SHA,
            'sealed_continuation_v1_QA_source_changed')
    ns = dict(previous.__dict__)
    ns['__file__'] = __file__
    for name, function in list(ns.items()):
        if isinstance(function, types.FunctionType) and function.__module__ == previous.__name__:
            local = types.FunctionType(function.__code__, ns, function.__name__, function.__defaults__, function.__closure__)
            local.__kwdefaults__ = function.__kwdefaults__
            ns[name] = local
    tree = ast.parse(inspect.getsource(previous.prepared_graph))
    transformed = []
    class CastMembership(ast.NodeTransformer):
        def visit_Compare(self, node):
            self.generic_visit(node)
            expected = "c['required_actor_assets'] == entry['full_clip_actor_ids']"
            if ast.unparse(node) == expected:
                require(len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq), 'single_cast_order_comparison_required')
                transformed.append(expected)
                return ast.copy_location(ast.Call(func=ast.Name(id='same_unique_cast', ctx=ast.Load()),
                    args=[node.left, node.comparators[0]], keywords=[]), node)
            return node
    tree = CastMembership().visit(tree)
    require(len(transformed) == 1, 'exactly_one_order_only_cast_assertion_must_change')
    ns['same_unique_cast'] = same_unique_cast
    exec(compile(ast.fix_missing_locations(tree), __file__, 'exec'), ns)
    return ns


_ns = _private_namespace()
# Explicit exports retain the independent source/pixel functions used by tests.
source_entry = _ns['source_entry']
series_inputs = _ns['series_inputs']
minimum_script = _ns['minimum_script']
library_reference_cards = _ns['library_reference_cards']
graph_pixel_routes = _ns['graph_pixel_routes']
prepared_graph = _ns['prepared_graph']


def for_run(run):
    return _ns['for_run'](run)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--prepared', action='store_true')
    p.add_argument('--preview', choices=IDS)
    p.add_argument('--asr', action='store_true')
    a = p.parse_args(argv); qa = for_run(a.run)
    if a.prepared:
        value = qa.validate_prepared(a.run)
        value['QA_source'] = bind(__file__)
        value['preserved_v1_source'] = bind(previous.__file__)
        folder = a.run/'independent_qa/continuation_v2_prepared'
        target = folder/(digest(value)+'.json')
        freeze(target, value)
        result = dict(status=value['status'], manifest=bind(target),
            segments=[{k:v for k,v in r.items() if k != 'binding'} for r in value['segments']],
            model_posts=0, old_QA_source_unchanged=True)
    elif a.preview:
        result = qa.preview_segment(a.run, a.preview)
    else:
        result = qa.qa(a.run, asr=a.asr)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
