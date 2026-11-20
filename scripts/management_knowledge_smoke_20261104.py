"""Offline CPU-only dependency/import smoke; synthetic text and scratch Chroma."""
import json
import os
from pathlib import Path
import sys
import time
import faulthandler

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/qa/management_dependency_20261104'
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', CUDA_VISIBLE_DEVICES='',
                  ANONYMIZED_TELEMETRY='False')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(OUT / 'staged'))


def main():
    faulthandler.dump_traceback_later(60, repeat=True)
    started = time.monotonic()
    result = {'production_data_touched': False, 'device': 'cpu', 'network_models': False}
    try:
        print('stage=import_project', flush=True)
        from src.rag_engine.knowledge_importer import KnowledgeImporter
        books = OUT / 'synthetic_books'
        books.mkdir(exist_ok=True)
        (books / 'fixture.txt').write_text('隔离测试：管理页面应显示真实导入结果。', encoding='utf-8')
        print('stage=initialize_cpu_embedding', flush=True)
        importer = KnowledgeImporter(persist_dir=str(OUT / 'scratch_chroma_stable_ids'))
        print('stage=import_synthetic_text', flush=True)
        result['import'] = importer.import_books(str(books))
        count = importer.db._collection.count()
        result['repeat_import'] = importer.import_books(str(books))
        result['idempotent_record_count'] = (count == importer.db._collection.count() == 1)
        found = importer.db.similarity_search('管理页面导入结果', k=1)
        result['retrieved_synthetic_source'] = bool(found and found[0].metadata.get('source_book') == 'fixture.txt')
        result['status'] = 'passed' if (result['import']['status'] == 'completed'
            and result['retrieved_synthetic_source'] and result['idempotent_record_count']) else 'failed'
    except Exception as exc:
        result.update(status='failed', error_type=type(exc).__name__)
        # Preserve diagnostics locally; no document body, credentials or parameters.
        result['dependency_error'] = str(exc)[:1200]
    result['elapsed_seconds'] = round(time.monotonic() - started, 2)
    faulthandler.cancel_dump_traceback_later()
    (OUT / 'SMOKE_RESULT.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
