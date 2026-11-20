"""Bounded local import accounting; dependencies are supplied by the importer."""
from pathlib import Path


def import_directory(directory, *, load, split, write, selected_files=None):
    result = dict(status='empty', files_total=0, files_processed=0, files_failed=0,
                  files_empty=0, chunks_prepared=0, chunks_imported=0,
                  batches_failed=0, batches_unconfirmed=0)
    directory = Path(directory)
    if not directory.is_dir():
        return dict(result, status='source_missing')
    files = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in {'.txt', '.epub', '.pdf'})
    if selected_files is not None:
        if (not isinstance(selected_files, (list, tuple)) or any(not isinstance(n, str)
                or Path(n).name != n or '/' in n or '\\' in n for n in selected_files)):
            raise ValueError('Invalid selected import files')
        chosen = set(selected_files)
        if not chosen <= {p.name for p in files}:
            raise ValueError('Selected import files missing')
        files = [p for p in files if p.name in chosen]
    result['files_total'] = len(files)
    chunks = []
    for path in files:
        try:
            documents = load(str(path))
            parts = split(documents) if documents else []
            if not parts:
                result['files_empty'] += 1
                continue
            for ordinal, part in enumerate(parts):
                part.metadata['source_book'] = path.name
                part.metadata['source_chunk_index'] = ordinal
            chunks.extend(parts)
            result['files_processed'] += 1
        except Exception:
            result['files_failed'] += 1
    result['chunks_prepared'] = len(chunks)
    for index in range(0, len(chunks), 100):
        batch = chunks[index:index + 100]
        try:
            ids = write(batch)
            if (not isinstance(ids, list) or len(ids) != len(batch)
                    or any(not isinstance(v, str) or not v for v in ids) or len(set(ids)) != len(ids)):
                result['batches_unconfirmed'] += 1
            else:
                result['chunks_imported'] += len(batch)
        except Exception:
            result['batches_failed'] += 1
    if result['files_failed'] or result['batches_failed'] or result['batches_unconfirmed']:
        result['status'] = 'partial' if result['chunks_imported'] else 'failed'
    elif result['chunks_imported'] and not result['files_empty']:
        result['status'] = 'completed'
    elif result['chunks_imported']:
        result['status'] = 'partial'
    return result


def write_stable_chunks(db, batch):
    """Retrying identical local input upserts the same chunks, without deleting history."""
    import hashlib
    import json
    ids = [hashlib.sha256(json.dumps([
        'knowledge-chunk/v1', part.metadata['source_book'],
        part.metadata['source_chunk_index'], part.page_content],
        ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest() for part in batch]
    return db.add_documents(batch, ids=ids)
