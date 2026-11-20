"""Knowledge counts are a read-only view, never a database initializer."""
from contextlib import closing
from pathlib import Path
import sqlite3


def embedding_dependency_ready():
    """Check metadata only; opening a page never imports Torch or initializes a model."""
    from importlib.metadata import version, PackageNotFoundError
    from packaging.version import Version, InvalidVersion
    try:
        return Version(version('sentence-transformers')) >= Version('5.7.0')
    except (PackageNotFoundError, InvalidVersion):
        return False


def read_status(path):
    path = Path(path).resolve()
    if not path.is_file():
        return {'status': 'absent'}
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            count = db.execute('SELECT COUNT(*) FROM embedding_metadata WHERE key=?', ('chroma:document',)).fetchone()[0]
            sources = [r[0] for r in db.execute(
                'SELECT DISTINCT string_value FROM embedding_metadata WHERE key=?', ('source_book',)) if r[0]]
        return {'status': 'available', 'chunks': count, 'sources': sources}
    except (OSError, sqlite3.Error):
        return {'status': 'unavailable'}


def render_import_result(st, result):
    if not isinstance(result, dict):
        st.warning('导入调用已返回，但没有可核验的导入回执；不能判断全部成功，请核对知识库状态。')
        return
    count = result.get('chunks_imported', 0)
    if result.get('status') == 'completed':
        st.success(f"知识库已确认写入 {count} 个片段，来自 {result['files_processed']} 份文件。")
    elif result.get('status') in {'empty', 'source_missing'}:
        st.warning('没有可导入的有效正文；未确认写入任何知识片段。请检查目录、文件类型与内容。')
    else:
        st.warning(f"导入未全部完成：已确认写入 {count} 个片段；文件失败 {result.get('files_failed', 0)} 份，"
                   f"写入失败 {result.get('batches_failed', 0)} 批，结果未确认 {result.get('batches_unconfirmed', 0)} 批。请核对后台记录，勿将其当作全部成功。")
        st.caption('失败或结果未确认的批次也可能已经部分写入；系统不会自动重试，请先核对回执。')
