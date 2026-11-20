"""Extract complete-chapter facts; dispatch frozen runs by their own version."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import corpus_production_v3 as legacy
from src.content_factory import corpus_production_v4 as whole_chapter
from src.content_factory import corpus_production_v5 as chapter_facts
from src.content_factory import corpus_production_v6 as chapter_materials
from src.content_factory import corpus_production_v7 as minimax_materials
from src.content_factory import corpus_production_v8 as temporal_materials
from src.content_factory import corpus_production_v9 as current


def coordinator(run):
    version = json.loads((Path(run) / 'PLAN.json').read_text(encoding='utf-8')).get('version')
    if version == current.VERSION:
        return current
    if version == temporal_materials.VERSION:
        return temporal_materials
    if version == minimax_materials.VERSION:
        return minimax_materials
    if version == chapter_materials.VERSION:
        return chapter_materials
    if version == chapter_facts.VERSION:
        return chapter_facts
    if version == whole_chapter.VERSION:
        return whole_chapter
    if version == legacy.VERSION:
        return legacy
    raise ValueError('unsupported_frozen_production_version')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'materials', 'local', 'adopt-core', 'prepare-cloud', 'cloud', 'status'])
    parser.add_argument('--run', required=True)
    parser.add_argument('--manifest')
    parser.add_argument('--previous-status')
    parser.add_argument('--user-statement')
    parser.add_argument('--group-chars', type=int, help='legacy option; new plans use complete chapters')
    parser.add_argument('--context-neighbors', type=int, default=1)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    if args.action == 'prepare':
        if not all((args.manifest, args.previous_status, args.user_statement)):
            parser.error('prepare requires manifest, previous-status and user-statement')
        if args.group_chars is not None:
            parser.error('new plans accept complete chapters; --group-chars is no longer used')
        value = current.prepare(args.manifest, args.run, previous_status=args.previous_status,
                        user_statement=args.user_statement, context_neighbors=args.context_neighbors, workers=args.workers)
        value = {k: value[k] for k in ('version', 'source_chapters', 'workers', 'cloud_models', 'materials_call_limit', 'production_call_limit')}
    elif args.action in ('materials', 'local'):
        value = coordinator(args.run).execute_local(args.run)
    elif args.action == 'adopt-core':
        selected = coordinator(args.run)
        if selected is not legacy:
            parser.error('whole-chapter plans preserve every paragraph; no legacy core adoption')
        value = selected.adopt_core_materials(args.run)
    elif args.action == 'prepare-cloud':
        coordinator(args.run).prepare_cloud(args.run)
        value = json.loads((Path(args.run) / 'CLOUD_EVIDENCE_BINDING.json').read_text(encoding='utf-8'))
    elif args.action == 'cloud':
        value = coordinator(args.run).execute_cloud(args.run)
    else:
        value = json.loads((Path(args.run) / 'STATE.json').read_text(encoding='utf-8'))
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
