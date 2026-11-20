import ast
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace as NS

import pytest
from streamlit.testing.v1 import AppTest

from src.rag_engine.knowledge_import_result import import_directory
from src.web.knowledge_status import read_status


def test_knowledge_state_is_ro_and_missing_does_not_create(tmp_path):
    path = tmp_path / 'missing/chroma.sqlite3'
    assert read_status(path) == {'status': 'absent'} and not path.exists()
    path = tmp_path / 'chroma.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE embedding_metadata(key,string_value)')
        db.executemany('INSERT INTO embedding_metadata VALUES(?,?)',
                       [('chroma:document', 'a'), ('source_book', 'fixture.txt')])
    before = path.read_bytes()
    assert read_status(path) == {'status': 'available', 'chunks': 1, 'sources': ['fixture.txt']}
    assert before == path.read_bytes()
    path.write_text('invalid')
    assert read_status(path) == {'status': 'unavailable'}


@pytest.mark.parametrize('outcome', ['complete', 'read_failure', 'write_failure', 'unknown', 'empty'])
def test_import_result_never_claims_failed_or_unknown_batch_succeeded(tmp_path, outcome):
    (tmp_path / 'fixture.txt').write_text('disposable synthetic test text')
    def load(path):
        if outcome == 'read_failure':
            raise ValueError('PRIVATE')
        return [] if outcome == 'empty' else [NS(metadata={})]
    def write(batch):
        if outcome == 'write_failure':
            raise ValueError('PRIVATE')
        return None if outcome == 'unknown' else ['fixture-id']
    result = import_directory(tmp_path, load=load, split=lambda docs: docs, write=write)
    assert result['status'] == {'complete': 'completed', 'empty': 'empty'}.get(outcome, 'failed')
    assert result['chunks_imported'] == (1 if outcome == 'complete' else 0)
    assert 'PRIVATE' not in str(result)


def test_sync_only_imports_copied_files(tmp_path):
    for name in ('old.txt', 'new.txt'):
        (tmp_path / name).write_text('fixture')
    loaded = []
    result = import_directory(tmp_path,
        load=lambda path: loaded.append(Path(path).name) or [NS(metadata={})],
        split=lambda docs: docs, write=lambda batch: ['id'], selected_files=['new.txt'])
    assert result['status'] == 'completed' and loaded == ['new.txt']
    with pytest.raises(ValueError):
        import_directory(tmp_path, load=None, split=None, write=None, selected_files=['../outside.txt'])


def page_function(name):
    source = (Path(__file__).parents[1] / 'src/web/app.py').read_text(encoding='utf-8-sig')
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(source, node)


def test_knowledge_page_view_does_not_import_models_and_partial_import_has_no_success(tmp_path, monkeypatch):
    from src.web.components import auth
    from src.shared.config import settings
    monkeypatch.setattr(auth, 'get_current_role', lambda: 'admin')
    monkeypatch.setattr('src.web.knowledge_status.embedding_dependency_ready', lambda: True)
    monkeypatch.setattr(settings, 'BOOKS_DIR', str(tmp_path / 'books'))
    calls = []
    class Importer:
        def __init__(self):
            calls.append('model_initialized_after_explicit_click')
        def import_books(self, *a, **kw):
            return {'status': 'partial', 'chunks_imported': 1, 'files_failed': 1}
    monkeypatch.setitem(sys.modules, 'src.rag_engine.knowledge_importer', NS(KnowledgeImporter=Importer))
    script = ('import streamlit as st\nfrom pathlib import Path\n'
              'from src.web.components.ui import page_header\n'
              'from src.web.components.auth import get_current_role,has_permission\n'
              + 'PROJECT_ROOT = Path(' + repr(str(tmp_path)) + ')\n'
              + page_function('page_books') + '\npage_books()\n')
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception and not calls
    assert not (tmp_path / 'data/chroma_db/chroma.sqlite3').exists()
    next(b for b in app.button if b.label == '🔃 重新导入全部').click().run()
    assert not app.exception and len(calls) == 1
    assert any('未全部完成' in x.value for x in app.warning) and not app.success


def test_opening_scheduler_never_starts_or_restarts_it(monkeypatch):
    events = []
    monkeypatch.setitem(sys.modules, 'src.scheduler.ui', NS(page_scheduler=lambda: events.append('render')))
    # If the page tries importing the old boot helper, no callable is available.
    monkeypatch.setitem(sys.modules, 'src.scheduler.runner', NS())
    app = AppTest.from_string(page_function('page_scheduler') + '\npage_scheduler()\n').run()
    assert not app.exception and events == ['render']
    app.run()
    assert not app.exception and events == ['render', 'render']
    startup = (Path(__file__).parents[1] / 'scripts/run_streamlit_web.py').read_text(encoding='utf-8')
    assert 'target=_start_background_services' in startup and 'start_scheduler()' in startup


def test_stable_chunk_ids_reuse_identical_inputs_but_preserve_sources_and_positions():
    from src.rag_engine.knowledge_import_result import write_stable_chunks
    saved = {}
    class DB:
        def add_documents(self, batch, ids):
            saved.update(zip(ids, batch))
            return ids
    a = NS(metadata={'source_book': 'a.txt', 'source_chunk_index': 0}, page_content='fixture')
    b = NS(metadata={'source_book': 'b.txt', 'source_chunk_index': 0}, page_content='fixture')
    ids = write_stable_chunks(DB(), [a, b])
    assert len(saved) == 2 and write_stable_chunks(DB(), [a, b]) == ids and len(saved) == 2
    c = NS(metadata={'source_book': 'a.txt', 'source_chunk_index': 1}, page_content='fixture')
    assert write_stable_chunks(DB(), [c])[0] not in ids


def test_search_failure_does_not_enable_disabled_remote_model_fallback(monkeypatch):
    from src.rag_engine.wisdom_retriever import WisdomRetriever
    from src.shared.config import settings
    monkeypatch.setattr(settings, 'ENABLE_HF_EMBEDDING_FALLBACK', False)
    obj = WisdomRetriever.__new__(WisdomRetriever)
    calls = []
    obj._build_huggingface_embedding = lambda: calls.append('forbidden remote fallback')
    assert obj._retry_with_huggingface() is False and not calls


def test_candidate_preview_never_queues_real_window_commands(monkeypatch):
    app = AppTest.from_file(str(Path(__file__).parents[1] / 'scripts/management_ui_preview_20261104.py'),
                            default_timeout=30).run()
    assert not app.exception
    assert app.button(key='global_account_issue_open_2').disabled
    app.selectbox[0].set_value('当前窗口就绪').run()
    assert not any(b.label == '结清重启前的旧窗口记录' for b in app.button)
    app.button(key='global_account_issue_open_2').click().run()
    assert not app.exception and app.session_state['preview_last_action']
