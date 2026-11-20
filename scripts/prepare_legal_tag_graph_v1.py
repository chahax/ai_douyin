"""Prepare immutable legal metadata graph and creative wire previews, offline only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trend_intelligence.legal_tag_graph_v1 import build_graph, validate_graph
from src.trend_intelligence.legal_tag_graph_report_v1 import render_graph_html, render_report
from src.content_factory.creative_legal_tag_graph_bridge_v1 import (
    build_packet, build_preview, build_wire, select_candidates,
)

VERSION = 'prepare_legal_tag_graph/v1'
ARTIFACT_NAMES = ('GRAPH.json', 'CANDIDATES.json', 'SOURCE_PACKET.json',
                  'DIRECTION_REQUEST_PREVIEW.json', 'DIRECTION_WIRE_PREVIEW.json',
                  'REPORT.md', 'GRAPH.html', 'MANIFEST.json')


def byte_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_digest(value) -> str:
    return byte_digest(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':')).encode('utf-8'))


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def _timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError) as exc:
        raise ValueError('--now must be an ISO timestamp with timezone') from exc
    if parsed.tzinfo is None:
        raise ValueError('--now must include a timezone')
    return parsed.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def prepare_bundle(*, source_path: Path, reference_path: Path, standards_path: Path,
                   legal_facts_path: Path, now: str, focus_label: str = '被迫离职',
                   family_id: str = 'family:labor') -> tuple[dict[str, bytes], dict]:
    """Read files and prepare all bytes before any write. Never creates a client."""
    sources = {'source': Path(source_path).resolve(), 'reference_fulltext': Path(reference_path).resolve(),
               'expression_standards': Path(standards_path).resolve(), 'legal_facts': Path(legal_facts_path).resolve()}
    raw = {key: path.read_bytes() for key, path in sources.items()}
    decode = lambda key: raw[key].decode('utf-8-sig')
    source = json.loads(decode('source'))
    standards = json.loads(decode('expression_standards'))
    facts = json.loads(decode('legal_facts'))
    reference = sources['reference_fulltext'].read_text(encoding='utf-8-sig')
    prepared_at = _timestamp(now)
    if datetime.fromisoformat(prepared_at.replace('Z','+00:00')) > datetime.now(timezone.utc):
        raise ValueError('preparation timestamp is in the future')
    graph = build_graph(source)
    validate_graph(graph, source)
    candidates = select_candidates(graph, family_id=family_id)
    packet = build_packet(source, graph, reference, standards, now=prepared_at,
                          focus_label=focus_label, family_id=family_id)
    preview = build_preview(packet, facts, now=prepared_at)
    wire = build_wire(packet, facts, now=prepared_at)
    for request in (preview, wire):
        if request.get('submitted') is not False or request.get('dispatch_allowed') is not False:
            raise ValueError('offline request unexpectedly permits dispatch')
    payloads = {'GRAPH.json': graph, 'CANDIDATES.json': candidates, 'SOURCE_PACKET.json': packet,
                'DIRECTION_REQUEST_PREVIEW.json': preview, 'DIRECTION_WIRE_PREVIEW.json': wire}
    content = {name: json_bytes(value) for name, value in payloads.items()}
    content['REPORT.md'] = render_report(graph, candidates, packet, prepared_at=prepared_at).encode('utf-8')
    content['GRAPH.html'] = render_graph_html(graph, candidates, packet, prepared_at=prepared_at).encode('utf-8')
    implementation_paths = [Path(__file__).resolve(), ROOT / 'src/trend_intelligence/legal_tag_graph_v1.py',
                            ROOT / 'src/trend_intelligence/legal_tag_graph_report_v1.py',
                            ROOT / 'src/content_factory/creative_legal_tag_graph_bridge_v1.py']
    manifest = {'schema': VERSION, 'prepared_at': prepared_at, 'collection_run_id': graph['collection_run_id'],
        'focus_label': focus_label, 'family_id': family_id, 'source_byte_sha256': byte_digest(raw['source']),
        'source_canonical_sha256': canonical_digest(source), 'graph_canonical_sha256': canonical_digest(graph),
        'packet_canonical_sha256': canonical_digest(packet),
        'input_files': {key: {'path': str(path), 'byte_sha256': byte_digest(raw[key])} for key, path in sources.items()},
        'implementation_files': {str(path.relative_to(ROOT)).replace('\\', '/'): byte_digest(path.read_bytes())
                                 for path in implementation_paths},
        'artifacts': {name: {'byte_sha256': byte_digest(value), 'bytes': len(value),
                            **({'canonical_sha256': canonical_digest(payloads[name])} if name in payloads else {})}
                      for name, value in sorted(content.items())},
        'execution': {'offline_only': True, 'new_collection_requests': 0, 'new_model_requests': 0,
                      'new_media_requests': 0, 'new_publish_requests': 0, 'submitted': False,
                      'dispatch_allowed': False, 'automatic_retry': False,
                      'budget_or_ledger_reset': False, 'creative_quality_passed': False,
                      'human_direction_confirmation_inherited': False},
        'summary': graph['summary'],
        'selected_candidate': {'candidate_id': packet['candidate']['candidate_id'],
                               'title': packet['candidate']['title'],
                               'support_video_count': packet['candidate']['support_video_count'],
                               'visible_author_count': packet['candidate']['visible_author_count']}}
    content['MANIFEST.json'] = json_bytes(manifest)
    return content, manifest


def write_bundle(output: Path, content: dict[str, bytes]) -> dict[str, str]:
    """Create only. Identical replay is safe; any conflict blocks before writes."""
    output = Path(output).resolve()
    if set(content) != set(ARTIFACT_NAMES):
        raise ValueError('complete declared artifact bundle required')
    if output.exists() and not output.is_dir():
        raise ValueError('output must be a directory')
    if output.exists():
        unexpected = {p.name for p in output.iterdir()} - set(ARTIFACT_NAMES)
        if unexpected:
            raise ValueError('output contains undeclared files; choose a new directory')
        for name, value in content.items():
            target = output / name
            if target.exists() and (not target.is_file() or target.read_bytes() != value):
                raise ValueError('immutable output conflict: ' + name)
    output.mkdir(parents=True, exist_ok=True)
    dispositions = {}
    for name, value in content.items():
        target = output / name
        if target.exists():
            dispositions[name] = 'identical_replay'
            continue
        try:
            with target.open('xb') as stream:
                stream.write(value)
        except FileExistsError:
            if target.read_bytes() != value:
                raise ValueError('concurrent immutable output conflict: ' + name)
            dispositions[name] = 'identical_replay'
        else:
            dispositions[name] = 'created'
    return dispositions


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--reference-fulltext', type=Path, required=True)
    parser.add_argument('--standards', type=Path, required=True)
    parser.add_argument('--legal-facts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--now', help='ISO UTC preparation time; use same value for identical replay')
    parser.add_argument('--focus-label', default='被迫离职')
    parser.add_argument('--family-id', default='family:labor')
    args = parser.parse_args(argv)
    try:
        content, manifest = prepare_bundle(source_path=args.source, reference_path=args.reference_fulltext,
            standards_path=args.standards, legal_facts_path=args.legal_facts, now=_timestamp(args.now),
            focus_label=args.focus_label, family_id=args.family_id)
        dispositions = write_bundle(args.output, content)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'blocked', 'error': str(exc), 'model_requests': 0,
                          'budget_or_ledger_reset': False}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({'status': 'offline_prepared', 'output': str(args.output.resolve()),
        'collection_run_id': manifest['collection_run_id'], 'summary': manifest['summary'],
        'selected_candidate': manifest['selected_candidate'], 'dispositions': dispositions,
        'submitted': False, 'new_model_requests': 0, 'creative_quality_passed': False}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
