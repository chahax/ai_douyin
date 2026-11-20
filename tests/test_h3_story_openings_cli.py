"""Read-only-source CLI checks; CPU preparation only, no Comfy or model calls."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from scripts import prepare_h3_story_openings as cli
from src.content_factory import visual_opening_frame as opening


def invoke(*arguments):
    return subprocess.run([sys.executable, str(Path(cli.__file__)), *map(str, arguments)],
                          capture_output=True, text=True, encoding='utf-8', timeout=45)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_help_has_only_preparation_action():
    result = invoke('--help')
    assert result.returncode == 0
    assert '{prepare}' in result.stdout and '--source' in result.stdout and '--out' in result.stdout


def test_real_source_prepare_then_idempotent_replay_preserves_original(tmp_path):
    source = cli.spatial.SPEC
    before = sha(source)
    out = tmp_path / 'derived'
    first = invoke('prepare', '--source', source, '--out', out)
    assert first.returncode == 0, first.stderr
    report = json.loads(first.stdout)
    assert report['model_calls'] == report['http_calls'] == 0
    assert report['media_dispatched'] is False and report['no_video_trim'] is True
    assert report['new_image_observation_created'] is False
    derived = json.loads((out / 'SOURCE_CASE.json').read_text(encoding='utf-8'))
    original = cli.core._entries(cli.core.binding(source))
    for old, new in zip(original, derived['shots']):
        assert new == dict(old, first_frame_policy=opening.POLICY)
    s02 = next(row for row in report['shots'] if row['shot_id'] == 'S02')
    assert s02['first_frame_visible_actors'] == ['su_mo']
    assert len(s02['clip_visible_actors']) == 3 and s02['framing'] == 'face_close'
    assert (out / 'spatial/SPATIAL_PLAN.json').exists()
    checkpoint = {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file()}
    second = invoke('--source', source, '--out', out)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout) == report
    assert {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file()} == checkpoint
    assert sha(source) == before


def test_output_cannot_be_source_parent_or_ancestor():
    source = cli.spatial.SPEC
    for forbidden in (source, source.parent, source.parent.parent):
        result = invoke('--source', source, '--out', forbidden)
        assert result.returncode != 0
        assert 'output_cannot_be_source_or_source_ancestor' in result.stderr


def test_conflicting_derived_record_is_preserved(tmp_path):
    out = tmp_path / 'conflict'
    out.mkdir()
    target = out / 'SOURCE_CASE.json'
    target.write_text('{"do_not_overwrite":true}', encoding='utf-8')
    before = target.read_bytes()
    result = invoke('--out', out)
    assert result.returncode != 0 and 'existing_preparation_record_changed' in result.stderr
    assert target.read_bytes() == before and not (out / 'spatial').exists()
