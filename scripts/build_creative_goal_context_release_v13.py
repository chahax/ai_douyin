"""Static code/document recovery snapshot; no production import or request replay.

The default prepare mode reads and checks inventories only.  --build is a distinct,
one-time operation, to be invoked after the coordinating agent confirms stability.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PARENT_REL = "data/development_checkpoints/creative_goal_context_release_20261013_v12"
DEST_REL = "data/development_checkpoints/creative_goal_context_release_20261013_v13"
QA_REL = "data/qa/goal_context_production_repair_20261013"
PARENT_PINS = {
    "MANIFEST.json": "8ff0fa38f712625dffef6562f467b58919f067c14cff735b9b74baca6213bac8",
    "CODE_CONTRACTS_AND_PREVIEWS.zip": "0827119884bd9dad93ff6658d8949a4560f5f8463b751b7ea59d4204c1b3d201",
    "VERIFICATION_REPORT.json": "b899b681c2fabff9d317925ef8cf5ea069c239343a16b2866006bc2d3599383e",
    "INDEPENDENT_READBACK.json": "a50733bbc18d4d28b38ad26dea22c60b9b9775ee92b8eaab3062ebaacac05089",
}
STABLE_SOURCE_PINS = {
    "src/content_factory/creative_full_review_contract_v4.py": "5f4ac922688302d882342cf43ec4c76e3de7bc6c1326f714704b023788441390",
    "src/content_factory/creative_full_review_contract_v5.py": "900a6cf72ad0136834f18d1baaf2456d3d29dba19d49ada77f881f4e8eee248a",
    "src/content_factory/creative_split_full_review_contract_v1.py": "83bc149a0911b0b8206ddea6edf1d61ca922f207752e13f0b7aea65b1c310222",
    "src/content_factory/creative_flat_lineage_verifier_v1.py": "1bf4bfdcdca7876d068c0021dd12b34c0404e2e0056a50aeb1808e23d4c7a338",
    QA_REL + "/SPLIT_REVIEW_NATIVE_547_551_552_DIAGNOSIS.json": "4d5a7cba9c9bd5d468f2ab9f47663c0c197aaab8e3e2d759fa0782d4ac789b78",
}
EXTRA_SOURCES = {
    "scripts/build_creative_goal_context_release_v13.py",
    "src/content_factory/creative_full_review_contract_v5.py",
    "src/content_factory/creative_split_full_review_contract_v1.py",
    "src/content_factory/creative_goal_context_workflow_v8.py",
    "scripts/creative_goal_context_dispatch_v6.py",
    "scripts/run_goal_context_text_production_v9.py",
    "scripts/record_split_full_review_continuation_v1.py",
    "tests/test_creative_full_review_contract_v5.py",
    "tests/test_creative_split_full_review_contract_v1.py",
    "tests/test_creative_split_full_review_contract_v1_independent.py",
    "tests/test_creative_goal_context_workflow_v8.py",
    "tests/test_creative_goal_context_workflow_v8_independent_audit.py",
    "tests/test_goal_context_text_production_v9_independent_audit.py",
    "docs/CREATIVE_SPLIT_FULL_REVIEW_REPAIR_PLAN_20261013.md",
    "docs/CREATIVE_SPLIT_FULL_REVIEW_CONTRACT_IMPLEMENTATION_20261013.md",
    QA_REL + "/SPLIT_REVIEW_NATIVE_547_551_552_DIAGNOSIS.json",
    QA_REL + "/split_contract_own_r4.xml",
    QA_REL + "/split_prior_guard_own_r1.xml",
    QA_REL + "/split_full_review_independent_r1.xml",
    QA_REL + "/split_contract_independent_r2.xml",
    QA_REL + "/split_workflow_producer_independent_r2.xml",
    QA_REL + "/workflow_v8_r3.xml",
}
PROHIBITED_NAMES = {
    "CALL_LEDGER.JSON", "RUN_CLAIM.JSON", "CLAIM.JSON", "USER_SCOPE.JSON",
    "AUTHORIZATION.JSON", "USER_CONTINUATION.JSON", "PRODUCTION_FREEZE.JSON",
    "TEST_FREEZE.JSON", "STATE.JSON", "PROGRESS.JSON", "SOURCE_GATE.JSON",
    "CERTIFIED_PARENT_LINEAGE.JSON", "DISPATCH.LOCK", "INPUTS.JSON",
}


def require(value: object, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def valid_relative(relative: str) -> None:
    require(isinstance(relative, str) and "\\" not in relative, "Use relative POSIX paths")
    rel = PurePosixPath(relative)
    require(not rel.is_absolute() and ".." not in rel.parts and str(rel) == relative, "Unsafe relative path: " + relative)
    require(relative.startswith(("src/", "scripts/", "tests/", "docs/", "config/", "data/qa/")), "Source domain forbidden: " + relative)
    require(rel.suffix in {".py", ".md", ".json", ".xml"}, "File type forbidden: " + relative)
    require(rel.name.upper() not in PROHIBITED_NAMES, "Production state forbidden: " + relative)
    require(not (rel.suffix == ".json" and rel.name.lower().startswith(
        ("call_", "native_", "request_body", "response_body", "inherited_native", "inherited_diagnostics"))),
        "Raw production material forbidden: " + relative)
    require(not any(part.lower() in {"source_at_dispatch", "synthetic_project", "call_evidence", "credentials"}
                    or part.lower().startswith(("pytest_", "split_independent_tmp", "split_workflow_producer_tmp"))
                    for part in rel.parts), "Runtime material forbidden: " + relative)


def source_path(root: Path, relative: str) -> Path:
    valid_relative(relative)
    resolved = (root / relative).resolve()
    require(resolved.is_relative_to(root.resolve()), "Source escapes workspace: " + relative)
    return resolved


def no_profile_credentials(value: object) -> None:
    if isinstance(value, dict):
        prohibited = {"api_key", "apikey", "secret", "password", "access_token",
                      "refresh_token", "authorization", "cookie"}
        require(not prohibited.intersection(str(key).lower() for key in value), "Credential-bearing profile forbidden")
        for item in value.values():
            no_profile_credentials(item)
    elif isinstance(value, list):
        for item in value:
            no_profile_credentials(item)


def parent_checkpoint(root: Path) -> tuple[dict, dict[str, str]]:
    """Validate the immutable parent archive and all copied members; no old code runs."""
    parent = root / PARENT_REL
    fingerprint = {}
    for name, expected in PARENT_PINS.items():
        fingerprint[name] = sha((parent / name).read_bytes())
        require(fingerprint[name] == expected, "Parent artifact changed: " + name)
    manifest = json.loads((parent / "MANIFEST.json").read_bytes())
    require(manifest.get("schema") == "creative_goal_context_release/v12", "Wrong parent schema")
    require(manifest["zip_sha256"] == PARENT_PINS["CODE_CONTRACTS_AND_PREVIEWS.zip"], "Parent ZIP binding differs")
    files, sources = manifest["files"], manifest["source_files"]
    require(set(files) == set(sources) | {"README.md"}, "Parent source/member coverage differs")
    require(manifest["source_members"] == len(sources) and manifest["members_verified"] == len(files), "Parent counts differ")
    require(set(manifest["file_sizes"]) == set(files), "Parent file length coverage differs")
    for relative in sources:
        valid_relative(relative)
        require(sources[relative] == files[relative], "Parent source SHA differs: " + relative)
    observed = {str(path.relative_to(parent / "FILES")).replace("\\", "/")
                for path in (parent / "FILES").rglob("*") if path.is_file()}
    require(observed == set(files), "Parent copied inventory differs")
    with zipfile.ZipFile(parent / "CODE_CONTRACTS_AND_PREVIEWS.zip") as archive:
        require(archive.testzip() is None, "Parent ZIP CRC failure")
        require(len(archive.namelist()) == len(files) and set(archive.namelist()) == set(files), "Parent ZIP inventory differs")
        for relative, expected in files.items():
            copied = (parent / "FILES" / relative).read_bytes()
            zipped = archive.read(relative)
            require(copied == zipped and sha(copied) == expected, "Parent member differs: " + relative)
            require(len(copied) == manifest["file_sizes"][relative], "Parent member length differs: " + relative)
            fingerprint["FILES/" + relative] = expected
    require((parent / "README.md").read_bytes() == (parent / "FILES/README.md").read_bytes(), "Parent README differs")
    fingerprint["README.md"] = files["README.md"]
    fingerprint["BUILD_SNAPSHOT.py"] = sha((parent / "BUILD_SNAPSHOT.py").read_bytes())
    require(fingerprint["BUILD_SNAPSHOT.py"] == manifest["builder_sha256"], "Parent builder differs")
    return manifest, fingerprint


def verify_parent_unchanged(root: Path, fingerprint: dict[str, str]) -> None:
    for relative, expected in fingerprint.items():
        require(sha((root / PARENT_REL / relative).read_bytes()) == expected, "Parent changed during verification: " + relative)


def static_python_closure(root: Path, seeds: set[str]) -> set[str]:
    """Resolve local AST imports, including function imports, without executing them."""
    seen, pending = set(), list(seeds)
    while pending:
        relative = pending.pop()
        if relative in seen:
            continue
        path = source_path(root, relative)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        seen.add(relative)
        package = PurePosixPath(relative).parts[:-1]
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                prefix = ".".join(package[:len(package) - node.level + 1]) if node.level else ""
                module = ".".join(part for part in (prefix, node.module) if part)
                if module:
                    names.append(module)
                names.extend(".".join(part for part in (module, item.name) if part)
                             for item in node.names if item.name != "*")
        for name in names:
            module_path = root.joinpath(*name.split("."))
            for candidate in (module_path.with_suffix(".py"), module_path / "__init__.py"):
                if candidate.is_file():
                    child = str(candidate.relative_to(root)).replace("\\", "/")
                    valid_relative(child)
                    if child not in seen:
                        pending.append(child)
    return seen


def inventory(root: Path, extras: set[str]) -> tuple[dict, dict, dict[str, str]]:
    parent, fingerprint = parent_checkpoint(root)
    explicit = set(parent["source_files"]) | EXTRA_SOURCES | extras
    for relative in explicit:
        source_path(root, relative)
    missing = sorted(path for path in explicit if not source_path(root, path).is_file())
    closure = static_python_closure(root, {p for p in explicit if p.endswith(".py") and p not in missing})
    if (root / "tests/conftest.py").is_file():
        closure |= static_python_closure(root, {"tests/conftest.py"})
    sources = sorted(explicit | closure)
    report = {
        "schema": "creative_goal_context_release/v13_prepare",
        "parent_checkpoint": str(root / PARENT_REL), "destination": str(root / DEST_REL),
        "parent_source_members_verified": len(parent["source_files"]),
        "parent_archive_members_verified": len(parent["files"]),
        "explicit_additions": sorted((EXTRA_SOURCES | extras) - set(parent["source_files"])),
        "source_files": sources, "static_python_dependency_files": sorted(closure),
        "missing_sources": missing, "prepared_complete": not missing,
        "final_snapshot_created": False, "source_bytes_copied": False,
        "production_modules_imported": False, "paid_calls": 0, "media_calls": 0,
    }
    verify_parent_unchanged(root, fingerprint)
    return report, parent, fingerprint


README = """# 可恢复独立代码与文档副本 v13（2026-10-13）

本包以已核验 v12 source_files 清单为底，复制稳定工作区代码/文档，另纳入 review/v5 零项协议、两份同源原生全文审查合同、workflow_v8、dispatch_v6、producer_v9、继续授权登记代码、修复计划、指定离线测试和七源诊断。静态 AST 收入本地 Python 导入依赖，打包没有 import 或运行生产入口。FILES/ 和 CODE_CONTRACTS_AND_PREVIEWS.zip 成员/字节一致，MANIFEST.json 逐文件记录 SHA-256 和长度。

v12 和更早副本保持原样。若后续内容不满意，可以在新的独立目录恢复本包代码，或对照 v12。恢复范围只有代码、文档及明确的离线证据；没有复制生产账本、claims、冻结、scope、TASKS 数据库、真实授权记录、凭据、素材或媒体。授权登记脚本是代码，不是新授权；QA 来源路径/SHA 和请求预览只用于诊断，不是可重放生产任务。

不得覆盖或回滚原工作区的消费账本、scope、claims、冻结、回执、数据库、进度、素材、媒体或凭据；不得清零调用、token、失败与未知预留，不得重启旧 RUN_CLAIM 或重派历史请求。恢复代码不授予任何新增付费调用、媒体或发布权限。动态历史绑定、第三方库和运行环境仍需原项目，该包不是整个运营环境的独立封装。

指定历史失败与较早 XML 原样保留，各套重叠测试不能相加作为独立总数。workflow_v8_r3.xml 是 fresh 接线修复前的回执，不能证明当前 workflow_v8 的新修复已通过；修复后的工作流/生产接线回归在包外另行记录，不能追加改写本副本。新协议将空覆盖表从原生 Schema 省略，仅在内部确定性视图恢复零项；两包是两份真实同源响应，不冒充单份原生整审。551/552 仍为失败证据，不因离线回演改变结论。离线通过不证明模型语义判断或创作质量，实际文本、导演、表演、制作交接与视频各按原生回执判断；视频仍由用户人工审查。

此次副本构建为 0 模型、0 媒体、0 发布。BUILD_SNAPSHOT.py 为静态一次性构建审计，仅 --build 会创建新副本，遇已有 v13 则拒绝；它不是恢复或生产运行程序。
"""


def save_new(dest: Path, relative: str, raw: bytes) -> None:
    path = (dest / relative).resolve()
    require(path.is_relative_to(dest.resolve()), "Snapshot write escapes destination")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def build(root: Path, extras: set[str], pins: dict[str, str]) -> dict:
    dest = root / DEST_REL
    require(not dest.exists(), "Refuse existing v13 snapshot; never overwrite or rerun")
    prepared, parent, fingerprint = inventory(root, extras)
    require(prepared["prepared_complete"], "Missing sources: " + ", ".join(prepared["missing_sources"]))
    captured, source_hashes = {}, {}
    for relative in prepared["source_files"]:
        raw = source_path(root, relative).read_bytes()
        if relative.startswith("config/"):
            no_profile_credentials(json.loads(raw))
        captured[relative], source_hashes[relative] = raw, sha(raw)
    for relative, expected in (STABLE_SOURCE_PINS | pins).items():
        require(source_hashes.get(relative) == expected, "Final stable binding differs: " + relative)
    builder_raw = Path(__file__).read_bytes()
    require(captured["scripts/build_creative_goal_context_release_v13.py"] == builder_raw, "Builder changed during capture")
    captured["README.md"] = README.encode("utf-8")
    for relative, expected in source_hashes.items():
        require(sha(source_path(root, relative).read_bytes()) == expected, "Source changed during capture: " + relative)
    verify_parent_unchanged(root, fingerprint)
    dest.mkdir(parents=True, exist_ok=False)
    save_new(dest, "BUILD_SNAPSHOT.py", builder_raw)
    save_new(dest, "README.md", captured["README.md"])
    for relative, raw in captured.items():
        save_new(dest, "FILES/" + relative, raw)
    archive_path = dest / "CODE_CONTRACTS_AND_PREVIEWS.zip"
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, raw in sorted(captured.items()):
            archive.writestr(relative, raw)
    with zipfile.ZipFile(archive_path) as archive:
        require(archive.testzip() is None, "New ZIP CRC failure")
        require(len(archive.namelist()) == len(captured) and set(archive.namelist()) == set(captured), "New ZIP member coverage differs")
        for relative, raw in captured.items():
            require((dest / "FILES" / relative).read_bytes() == archive.read(relative) == raw, "Copy/ZIP readback differs: " + relative)
    for relative, expected in source_hashes.items():
        require(sha(source_path(root, relative).read_bytes()) == expected, "Source changed during snapshot: " + relative)
    verify_parent_unchanged(root, fingerprint)
    manifest = {
        "schema": "creative_goal_context_release/v13", "verified_at": datetime.now(timezone.utc).isoformat(),
        "files": {relative: sha(raw) for relative, raw in sorted(captured.items())},
        "source_files": source_hashes, "file_sizes": {relative: len(raw) for relative, raw in sorted(captured.items())},
        "source_members": len(source_hashes), "members_verified": len(captured),
        "static_python_dependency_files": prepared["static_python_dependency_files"],
        "python_static_dependency_count": len(prepared["static_python_dependency_files"]),
        "dependencies_discovered_without_import_or_execution": True,
        "zip_sha256": sha(archive_path.read_bytes()), "builder_sha256": sha(builder_raw),
        "stable_source_bindings": STABLE_SOURCE_PINS | pins,
        "copy_bytes_equal": True, "zip_bytes_equal": True, "source_stable_during_capture": True,
        "credential_ledger_media_copied": False, "production_freeze_scope_claim_ledger_progress_modified": False,
        "paid_calls": 0, "media_calls": 0, "publishing_calls": 0,
        "incremental_on": "creative_goal_context_release_20261013_v12",
        "parent_manifest_sha256": PARENT_PINS["MANIFEST.json"], "parent_zip_sha256": parent["zip_sha256"],
        "parent_artifact_hashes": PARENT_PINS, "older_snapshots_preserved": True,
        "evidence_scope": {
            "workflow_v8_r3": "before fresh-context repair; not proof for current workflow",
            "current_fresh_workflow_producer_regression": "outside this immutable snapshot, separately reported",
            "snapshot_verification": "copy/ZIP/source hashes only; no creative-quality claim",
        },
        "restore": "code/documents into an independent directory only; no usage rollback or old request replay",
    }
    manifest_raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    save_new(dest, "MANIFEST.json", manifest_raw)
    require((dest / "MANIFEST.json").read_bytes() == manifest_raw, "Manifest readback differs")
    saved = json.loads((dest / "MANIFEST.json").read_bytes())
    with zipfile.ZipFile(archive_path) as archive:
        for relative, expected in saved["files"].items():
            copied, zipped = (dest / "FILES" / relative).read_bytes(), archive.read(relative)
            require(sha(copied) == sha(zipped) == expected, "Persisted SHA readback differs: " + relative)
            require(len(copied) == len(zipped) == saved["file_sizes"][relative], "Persisted length differs: " + relative)
    report = {
        "snapshot_path": str(dest), "manifest_sha256": sha(manifest_raw), "zip_sha256": saved["zip_sha256"],
        "source_members": saved["source_members"], "members_verified": saved["members_verified"],
        "python_static_dependency_count": saved["python_static_dependency_count"],
        "manifest_copy_and_zip_readback_verified": True, "source_stable_during_capture": True,
        "v12_preserved": True, "credential_ledger_media_copied": False,
        "production_freeze_scope_claim_ledger_progress_modified": False,
        "paid_calls": 0, "media_calls": 0, "publishing_calls": 0,
    }
    report_raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    save_new(dest, "VERIFICATION_REPORT.json", report_raw)
    require((dest / "VERIFICATION_REPORT.json").read_bytes() == report_raw, "Report readback differs")
    report["verification_report_sha256"] = sha(report_raw)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Create v13 once after explicit stability confirmation")
    parser.add_argument("--extra", action="append", default=[], help="Explicit additional code/document/offline evidence path")
    parser.add_argument("--pin", action="append", default=[], help="Final explicit path=SHA256 binding")
    parser.add_argument("--prepare-report", action="store_true", help="Save a new inventory-only QA preview, never the snapshot")
    args = parser.parse_args()
    extras = set(args.extra)
    pins = {}
    for item in args.pin:
        relative, sep, expected = item.partition("=")
        valid_relative(relative)
        require(sep and len(expected) == 64 and all(c in "0123456789abcdef" for c in expected), "Invalid final SHA binding")
        require(relative not in STABLE_SOURCE_PINS or STABLE_SOURCE_PINS[relative] == expected, "Cannot override established stable binding")
        pins[relative] = expected
        extras.add(relative)
    require(not (args.build and args.prepare_report), "Prepare-report is inventory-only")
    result = build(ROOT, extras, pins) if args.build else inventory(ROOT, extras)[0]
    if args.prepare_report:
        preview_path = ROOT / QA_REL / "V13_RECOVERY_SNAPSHOT_PREVIEW.json"
        with preview_path.open("xb") as stream:
            stream.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        print(json.dumps({
            "preview_path": str(preview_path), "preview_sha256": sha(preview_path.read_bytes()),
            "source_members": len(result["source_files"]),
            "static_python_dependency_count": len(result["static_python_dependency_files"]),
            "missing_sources": result["missing_sources"],
            "parent_archive_members_verified": result["parent_archive_members_verified"],
            "final_snapshot_created": False, "source_bytes_copied": False,
        }, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
