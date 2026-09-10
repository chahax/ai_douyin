"""Local, keyboard-accessible graph component. Selection never executes a node."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

_graph = components.declare_component('studio_flow_graph', path=str(Path(__file__).with_name('flow_graph')))


def flow_graph(nodes: list[dict], edges: list[dict], *, key: str, title: str,
               description: str = '', selected: str | None = None) -> dict[str, str] | None:
    """Return only validated node/edge selections; unknown client payloads are ignored."""
    ids = [item['id'] for item in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate graph node')
    edge_ids = [item['id'] for item in edges]
    if len(edge_ids) != len(set(edge_ids)):
        raise ValueError('Duplicate graph edge')
    if any(e['source'] not in ids or e['target'] not in ids for e in edges):
        raise ValueError('Graph edge references an unknown node')
    result = _graph(nodes=nodes, edges=edges, title=title, description=description,
                    selected=selected, key=key, default=None)
    return validate_selection(result, nodes, edges)


def validate_selection(value: Any, nodes: list[dict], edges: list[dict]) -> dict[str, str] | None:
    if not isinstance(value, dict) or value.get('kind') not in {'node', 'edge'}:
        return None
    pool = nodes if value['kind'] == 'node' else edges
    if not isinstance(value.get('id'), str) or value['id'] not in {item['id'] for item in pool}:
        return None
    return {'kind': value['kind'], 'id': value['id']}


def sequence_graph(steps: list[tuple[str, str, str]], *, key: str, title: str, description: str = ''):
    """Small conceptual process used to introduce a page before its controls."""
    nodes = [dict(id=str(i), label=label, subtitle='步骤 ' + str(i + 1), description=copy,
                  status=status, column=i, row=0, facts=[]) for i, (label, copy, status) in enumerate(steps)]
    edges = [dict(id=f'{i}-{i+1}', source=str(i), target=str(i+1), label='衔接说明',
                  description=f'完成「{steps[i][0]}」后进入「{steps[i+1][0]}」。这是操作顺序说明，不代表已自动执行。',
                  status='操作指引', facts=[]) for i in range(len(steps)-1)]
    return flow_graph(nodes, edges, key=key, title=title, description=description)
