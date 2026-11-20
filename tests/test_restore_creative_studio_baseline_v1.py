import hashlib
import json
import zipfile
from pathlib import Path
import pytest
from scripts.restore_creative_studio_baseline_v1 import verify_checkpoint, extract_new


def checkpoint(root, name="src/example.py"):
    out = root / "checkpoint"
    out.mkdir()
    raw = b"example = True\n"
    with zipfile.ZipFile(out / "BASELINE_CODE_AND_CONTEXT.zip", "w") as z:
        z.writestr(name, raw)
    m = {"schema": "creative_studio_development_baseline/v1",
        "archive_sha256": hashlib.sha256((out / "BASELINE_CODE_AND_CONTEXT.zip").read_bytes()).hexdigest(),
        "files": [{"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}],
        "protected_production_files": []}
    (out / "BASELINE_MANIFEST.json").write_text(json.dumps(m), encoding="utf-8")
    return out


def test_restore_new_copy_and_forbid_overwrite(tmp_path):
    cp = checkpoint(tmp_path)
    target = tmp_path / "restore"
    result = extract_new(cp, target, project=tmp_path)
    assert result["original_workspace_overwritten"] is False
    assert (target / "src/example.py").read_bytes() == b"example = True\n"
    with pytest.raises(ValueError, match="ALREADY_EXISTS"):
        extract_new(cp, target, project=tmp_path)


def test_archive_changed_rejected_before_target_creation(tmp_path):
    cp = checkpoint(tmp_path)
    with (cp / "BASELINE_CODE_AND_CONTEXT.zip").open("ab") as f:
        f.write(b"tamper")
    with pytest.raises(ValueError, match="ARCHIVE_CHANGED"):
        extract_new(cp, tmp_path / "restore", project=tmp_path)
    assert not (tmp_path / "restore").exists()


@pytest.mark.parametrize("name", ["../escape.py", "/absolute.py", "C:/escape.py", "src\\escape.py"])
def test_unsafe_archive_path_rejected(tmp_path, name):
    with pytest.raises(ValueError, match="UNSAFE_PATH"):
        verify_checkpoint(checkpoint(tmp_path, name))


def test_target_outside_or_root_forbidden(tmp_path):
    cp = checkpoint(tmp_path)
    for target in (tmp_path, tmp_path.parent / "outside"):
        with pytest.raises(ValueError, match="WITHIN_WORKSPACE"):
            extract_new(cp, target, project=tmp_path)
