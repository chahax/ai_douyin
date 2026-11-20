"""Verify/extract the saved development baseline into a NEW isolated directory.

No in-place rollback, deletion, credentials restoration, or ledger reset exists.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKPOINT = PROJECT / "data/development_checkpoints/creative_studio_baseline_20261012"


def sha_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def verify_checkpoint(checkpoint=DEFAULT_CHECKPOINT, *, check_protected=False, project=PROJECT):
    checkpoint = Path(checkpoint).resolve()
    manifest = json.loads((checkpoint / "BASELINE_MANIFEST.json").read_text(encoding="utf-8"))
    archive = checkpoint / "BASELINE_CODE_AND_CONTEXT.zip"
    if manifest.get("schema") != "creative_studio_development_baseline/v1":
        raise ValueError("BASELINE_MANIFEST_INVALID")
    if sha_bytes(archive.read_bytes()) != manifest["archive_sha256"]:
        raise ValueError("BASELINE_ARCHIVE_CHANGED")
    names = [row["path"] for row in manifest["files"]]
    if len(names) != len(set(names)):
        raise ValueError("BASELINE_DUPLICATE_PATH")
    for name in names:
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
            raise ValueError("BASELINE_UNSAFE_PATH")
    with zipfile.ZipFile(archive) as z:
        if set(z.namelist()) != set(names) or len(z.namelist()) != len(names):
            raise ValueError("BASELINE_ENTRY_MISMATCH")
        for row in manifest["files"]:
            info = z.getinfo(row["path"])
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("BASELINE_SYMLINK_FORBIDDEN")
            raw = z.read(info)
            if len(raw) != row["bytes"] or sha_bytes(raw) != row["sha256"]:
                raise ValueError("BASELINE_FILE_CHANGED")
    if check_protected:
        for row in manifest["protected_production_files"]:
            p = (Path(project) / row["path"]).resolve()
            if not p.is_relative_to(Path(project).resolve()) or sha_bytes(p.read_bytes()) != row["sha256"]:
                raise ValueError("PROTECTED_PRODUCTION_CHANGED: " + row["path"])
    return manifest


def extract_new(checkpoint, target, *, project=PROJECT):
    manifest = verify_checkpoint(checkpoint)
    target = Path(target).resolve()
    project = Path(project).resolve()
    if target == project or not target.is_relative_to(project):
        raise ValueError("RESTORE_TARGET_MUST_BE_NEW_DIRECTORY_WITHIN_WORKSPACE")
    if target.exists():
        raise ValueError("RESTORE_TARGET_ALREADY_EXISTS")
    target.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(Path(checkpoint) / "BASELINE_CODE_AND_CONTEXT.zip") as z:
        for row in manifest["files"]:
            p = (target / row["path"]).resolve()
            if not p.is_relative_to(target):
                raise ValueError("RESTORE_PATH_ESCAPE")
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("xb") as f:
                f.write(z.read(row["path"]))
            if sha_bytes(p.read_bytes()) != row["sha256"]:
                raise ValueError("RESTORE_COPY_FAILED")
    report = {"status": "isolated_baseline_copy_verified", "target": str(target),
        "files": len(manifest["files"]), "ledger_reset": False, "original_workspace_overwritten": False,
        "note": "Code/context copy only; original production history, media and environment remain in the original workspace."}
    (target / "RESTORE_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "extract"))
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--check-protected", action="store_true")
    args = parser.parse_args()
    if args.command == "extract":
        if args.target is None:
            parser.error("extract requires --target (a new directory)")
        result = extract_new(args.checkpoint, args.target)
    else:
        m = verify_checkpoint(args.checkpoint, check_protected=args.check_protected)
        result = {"status": "baseline_verified", "files": len(m["files"]),
            "protected_production_checked": args.check_protected, "archive_sha256": m["archive_sha256"]}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
