"""Read-only, epoch-scoped replacement for repeated *certified* ancestor guards.

This module does not create a runtime, dispatch, mutate history, or certify its
own semantics. A new entry first calls the unchanged full historical guard once
under a read observer. Only that successful checkpoint can create a certificate.
Later epochs rehash its complete observed/static dependency set and inventories.
The certificate itself must be bound by the new entry's immutable freeze.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import builtins
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
from typing import Callable, Iterable
from urllib.parse import parse_qs, unquote, urlsplit

# A lazy ancestor import inside our observer would capture its SQLite wrapper
# as v1._RAW_SQL and break v1's verified in-memory decoding. Bootstrap the
# unchanged ancestor before interception; do not relax the read-only observer.
from . import creative_flat_lineage_verifier_v1 as historical_native_verifier
from . import creative_flat_lineage_verifier_v2 as prior_native_verifier
from . import creative_flat_lineage_verifier_v3 as prior_strict_native_verifier
from . import creative_flat_lineage_verifier_v4 as prior_compact_native_verifier
from . import creative_flat_lineage_verifier_v5 as prior_evidence_role_native_verifier

VERSION = "creative_flat_lineage_verifier/v6"
_OBSERVER_LOCK = threading.Lock()
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RECEIPT = re.compile(r"call_[0-9]+_[a-zA-Z0-9_]{1,90}\.json\Z")
_INHERITED_KEYS = ("calls_started", "reported_tokens", "calls_with_known_usage",
                   "unknown_token_reservations", "pending_ordinals")


class LineageVerificationError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise LineageVerificationError("duplicate JSON key")
            out[key] = value
        return out
    def nonfinite(value):
        raise LineageVerificationError("nonfinite JSON constant: " + value)
    try:
        value = json.loads(raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw,
                           object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LineageVerificationError("complete UTF-8 JSON required") from exc
    def finite(item):
        if isinstance(item, float) and not math.isfinite(item):
            raise LineageVerificationError("nonfinite JSON overflow")
        if isinstance(item, dict):
            for child in item.values(): finite(child)
        elif isinstance(item, list):
            for child in item: finite(child)
    finite(value)
    if not isinstance(value, dict):
        raise LineageVerificationError("complete JSON object required")
    return value


def _absolute(path):
    return str(Path(path).resolve())


def _inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    try: path.relative_to(root)
    except ValueError as exc:
        raise LineageVerificationError("path escapes bound root: " + str(path)) from exc
    return path


class VerificationCycle:
    """One transient bytes/SHA/JSON cache. Never retain it across dispatches."""
    def __init__(self):
        self._bytes = {}
        self._json = {}
        self._sha = {}
        self._expected = {}
        self.read_counts = {}

    def read_bytes(self, path):
        key = _absolute(path)
        if key not in self._bytes:
            try:
                with _RAW_OPEN(key, "rb") as stream:
                    self._bytes[key] = stream.read()
            except OSError as exc:
                raise LineageVerificationError("missing/unreadable dependency: " + key) from exc
            self.read_counts[key] = 1
        return self._bytes[key]

    def sha(self, path):
        key = _absolute(path)
        if key not in self._sha:
            self._sha[key] = hashlib.sha256(self.read_bytes(key)).hexdigest()
        return self._sha[key]

    def json(self, path):
        key = _absolute(path)
        if key not in self._json:
            self._json[key] = strict_json(self.read_bytes(key))
        return deepcopy(self._json[key])

    def verify(self, path, expected):
        key = _absolute(path)
        if not isinstance(expected, str) or not _SHA.fullmatch(expected):
            raise LineageVerificationError("invalid dependency SHA: " + key)
        if key in self._expected and self._expected[key] != expected:
            raise LineageVerificationError("conflicting dependency SHA: " + key)
        self._expected[key] = expected
        if self.sha(key) != expected:
            raise LineageVerificationError("dependency SHA changed: " + key)


# Kept before the temporary observer; cycles do not recursively observe themselves.
_RAW_OPEN = builtins.open
_RAW_SCANDIR = os.scandir
_RAW_SQL = sqlite3.connect
_RAW_STAT = os.stat


def _probe_fact(path):
    try: data = _RAW_STAT(path)
    except (FileNotFoundError, NotADirectoryError): return {"exists": False}
    kind = "file" if stat.S_ISREG(data.st_mode) else "directory" if stat.S_ISDIR(data.st_mode) else "other"
    return {"exists": True, "type": kind}


def _inventory(directory):
    try:
        with _RAW_SCANDIR(directory) as entries:
            return sorted([entry.name, "directory" if entry.is_dir(follow_symlinks=False)
                           else "symlink" if entry.is_symlink() else "file"] for entry in entries)
    except OSError as exc:
        raise LineageVerificationError("unreadable dependency directory: " + str(directory)) from exc


class _ReadObserver:
    """Capture actual full-guard I/O, including files outside source manifests."""
    def __init__(self, cycle):
        self.cycle = cycle
        self.directories = {}
        self.sqlite_databases = set()
        self.probes = {}
        self._busy = False

    def record(self, path):
        if isinstance(path, int):
            raise LineageVerificationError("untraceable file-descriptor dependency")
        self.cycle.read_bytes(path)

    @contextmanager
    def activate(self):
        if not _OBSERVER_LOCK.acquire(blocking=False):
            raise LineageVerificationError("checkpoint observer already active")
        saved_open, saved_io, saved_scan, saved_sql = builtins.open, io.open, os.scandir, sqlite3.connect
        saved_list, saved_stat, saved_lstat = os.listdir, os.stat, os.lstat
        path_methods = {name: getattr(Path, name) for name in ("exists", "is_file", "is_dir", "is_symlink")}
        os_path_methods = {name: getattr(os.path, name) for name in ("exists", "lexists", "isfile", "isdir", "islink")}
        def observe_open(original):
            def opened(file, mode="r", *args, **kwargs):
                if not isinstance(mode, str) or any(flag in mode for flag in "wax+"):
                    raise LineageVerificationError("certified checkpoint must be read-only")
                self.record(file)
                return original(file, mode, *args, **kwargs)
            return opened
        def scanned(path="."):
            key = _absolute(path)
            members = _inventory(key)
            if key in self.directories and self.directories[key] != members:
                raise LineageVerificationError("directory changed during checkpoint: " + key)
            self.directories[key] = members
            return saved_scan(path)
        def listed(path="."):
            key = _absolute(path)
            members = _inventory(key)
            if key in self.directories and self.directories[key] != members:
                raise LineageVerificationError("directory changed during checkpoint: " + key)
            self.directories[key] = members
            return saved_list(path)
        def probed(original):
            def probe(path, *args, **kwargs):
                if self._busy: return original(path, *args, **kwargs)
                if isinstance(path, int) or kwargs.get("dir_fd") is not None:
                    raise LineageVerificationError("untraceable existence dependency")
                self._busy = True
                try:
                    key = _absolute(path)
                    fact = _probe_fact(key)
                    if key in self.probes and self.probes[key] != fact:
                        raise LineageVerificationError("existence dependency changed during checkpoint")
                    self.probes[key] = fact
                finally: self._busy = False
                return original(path, *args, **kwargs)
            return probe
        def predicate(original):
            def check(path, *args, **kwargs):
                if not self._busy:
                    self._busy = True
                    try:
                        key = _absolute(path)
                        fact = _probe_fact(key)
                        if key in self.probes and self.probes[key] != fact:
                            raise LineageVerificationError("existence dependency changed during checkpoint")
                        self.probes[key] = fact
                    finally: self._busy = False
                return original(path, *args, **kwargs)
            return check
        def connected(database, *args, **kwargs):
            if not kwargs.get("uri") or not isinstance(database, str):
                raise LineageVerificationError("checkpoint SQLite access must use read-only URI")
            uri = urlsplit(database)
            if uri.scheme != "file" or parse_qs(uri.query).get("mode") != ["ro"]:
                raise LineageVerificationError("traceable SQLite file URI required")
            path = unquote(uri.path)
            if os.name == "nt" and re.match(r"/[A-Za-z]:", path): path = path[1:]
            key = _absolute(path)
            self.record(key)
            self.sqlite_databases.add(key)
            for suffix in ("-wal", "-journal"):
                side = Path(key + suffix)
                if side.exists(): self.record(side)
            self.directories[str(Path(key).parent)] = _inventory(Path(key).parent)
            return saved_sql(database, *args, **kwargs)
        try:
            builtins.open, io.open = observe_open(saved_open), observe_open(saved_io)
            os.scandir, sqlite3.connect = scanned, connected
            os.listdir, os.stat, os.lstat = listed, probed(saved_stat), probed(saved_lstat)
            for name, original in path_methods.items(): setattr(Path, name, predicate(original))
            for name, original in os_path_methods.items(): setattr(os.path, name, predicate(original))
            yield self
        finally:
            builtins.open, io.open, os.scandir, sqlite3.connect = saved_open, saved_io, saved_scan, saved_sql
            os.listdir, os.stat, os.lstat = saved_list, saved_stat, saved_lstat
            for name, original in path_methods.items(): setattr(Path, name, original)
            for name, original in os_path_methods.items(): setattr(os.path, name, original)
            _OBSERVER_LOCK.release()


def _bind_manifest(cycle, project, manifest):
    if not isinstance(manifest, dict) or not manifest:
        raise LineageVerificationError("complete nonempty source manifest required")
    for name, expected in manifest.items():
        if not isinstance(name, str): raise LineageVerificationError("manifest path must be text")
        path = Path(name) if Path(name).is_absolute() else _inside(Path(project) / name, project)
        cycle.verify(path, expected)


def _outbound(cycle, project, directory, request, identity_sha):
    manifest = cycle.json(directory / "REQUEST_BODY_MANIFEST.json")
    m31_proof = (directory / "M31_WIRE_PREFLIGHT.json").exists()
    strict_proof = (directory / "DEEPSEEK_STRICT_WIRE_PREFLIGHT.json").exists()
    if strict_proof and m31_proof:
        raise LineageVerificationError("conflicting native transport proofs")
    proof = cycle.json(directory / ("DEEPSEEK_STRICT_WIRE_PREFLIGHT.json" if strict_proof else
                                   "M31_WIRE_PREFLIGHT.json" if m31_proof else "CAPABILITY_PREFLIGHT.json"))
    path = _inside(directory / manifest.get("body_file", ""), directory)
    raw = cycle.read_bytes(path)
    actual = strict_json(raw)
    if strict_proof and proof.get("schema") in (
            "creative_deepseek_strict_role_clients/v1/outbound_proof",
            "creative_deepseek_strict_role_clients/v2/outbound_proof",
            "creative_deepseek_strict_role_clients/v3/outbound_proof",
            "creative_deepseek_strict_role_clients/v4/outbound_proof"):
        if proof["schema"] == "creative_deepseek_strict_role_clients/v1/outbound_proof":
            from scripts import creative_deepseek_strict_role_clients_v1 as mapper
        elif proof["schema"] == "creative_deepseek_strict_role_clients/v2/outbound_proof":
            from scripts import creative_deepseek_strict_role_clients_v2 as mapper
        elif proof["schema"] == "creative_deepseek_strict_role_clients/v3/outbound_proof":
            from scripts import creative_deepseek_strict_role_clients_v3 as mapper
        else:
            from scripts import creative_deepseek_strict_role_clients_v4 as mapper
        from . import creative_deepseek_strict_schema_v1 as compiler
        cycle.read_bytes(mapper.__file__)
        cycle.read_bytes(compiler.__file__)
        expected = mapper.expected_wire_request(request)
        native_binding = mapper.protocol_binding(request)
        compiled = mapper.schema_compilation_manifest(request)
        if (cycle.json(directory / "DEEPSEEK_STRICT_SCHEMA_MANIFEST.json") != compiled
                or request.get("input_provenance", {}).get("source_protocol_binding") != native_binding
                or proof.get("source_protocol_binding_sha256") != digest(native_binding)
                or proof.get("schema_compilation_manifest_sha256") != digest(compiled)
                or proof.get("original_contract_sha256") != digest(request["structured_schema"])
                or proof.get("service_schema_sha256") != digest(expected["tools"][0]["function"]["parameters"])
                or proof.get("function_strict") is not True
                or proof.get("server_strict_schema_requested") is not True
                or proof.get("original_local_contract_validation_required") is not True
                or type(proof.get("max_wire_utf8_bytes")) is not int
                or not len(raw) <= proof["max_wire_utf8_bytes"] <= 600000):
            raise LineageVerificationError("strict native schema projection evidence differs")
    elif m31_proof and proof.get("schema") == "creative_m31_flash_role_clients/v1/outbound_proof":
        from scripts import creative_m31_flash_role_clients_v1 as mapper
        cycle.read_bytes(mapper.__file__)
        expected = mapper.expected_wire_request(request)
    elif proof.get("schema") == "creative_capability_role_clients/v2/outbound_capability_proof":
        from scripts import creative_capability_role_clients_v2 as mapper
        cycle.read_bytes(mapper.__file__)
        registry = cycle.json(Path(project) / "config/creative_provider_capabilities_20261012.json")
        expected = mapper.expected_wire_request(request, registry)
    else:
        raise LineageVerificationError("unverified native outbound adapter")
    sha = cycle.sha(path)
    if m31_proof or strict_proof:
        host = "api.minimax.cn" if request["role"] == "writer" else "api.deepseek.com"
        operation_path = "/beta/chat/completions" if strict_proof else "/v1/chat/completions"
        preflight_valid = (proof.get("status") == "wire_verified_before_send"
            and proof.get("mapped_fields") == sorted(actual)
            and proof.get("provider_endpoint_host") == host
            and proof.get("verified_endpoint_sha256") == digest(["POST", "https://" + host + operation_path])
            and proof.get("writer_reasoning_effort") == ("medium" if request["role"] == "writer" else None)
            and proof.get("server_stream_requested") is False and proof.get("server_schema_guarantee") is False
            and proof.get("new_provider_acceptance_verified") is False
            and proof.get("provider_received_request") is None and proof.get("calls_authorized_by_proof") is False)
    else:
        preflight_valid = (proof.get("original_body_sha256") == sha
            and proof.get("status") == "capability_preflight_passed"
            and proof.get("dispatch_before_verify") is False and proof.get("provider_endpoint_host_matched") is True)
    if (manifest.get("identity_sha256") != identity_sha or manifest.get("body_complete") is not True
        or manifest.get("raw_bytes_preserved") is not True or manifest.get("credential_redacted") is not False
        or manifest.get("stored_sha256") != sha or manifest.get("original_sha256") != sha
        or manifest.get("bytes") != len(raw) or manifest.get("original_bytes", len(raw)) != len(raw)
        or actual != expected or proof.get("identity_sha256") != identity_sha
        or proof.get("logical_request_sha256") != digest(request)
        or proof.get("expected_wire_sha256") != digest(expected)
        or proof.get("actual_wire_sha256") != digest(actual)
        or proof.get("actual_request_body_sha256") != sha
        or proof.get("body_bytes") != len(raw) or proof.get("full_wire_equals_mapped_logical_request") is not True
        or proof.get("messages_sha256") != digest(request["messages"])
        or proof.get("structured_schema_sha256") != digest(request["structured_schema"])
        or not preflight_valid
        or type(proof.get("SDK_max_retries")) is not int or proof["SDK_max_retries"] != 0
        or proof.get("HTTP_follow_redirects") is not False or proof.get("endpoint_method") != "POST"
        or proof.get("endpoint_path") != ("/beta/chat/completions" if strict_proof else "/v1/chat/completions")
        or proof.get("automatic_retry") is not False):
        raise LineageVerificationError("native outbound request/protocol evidence differs")
    return expected


def _receipt(cycle, project, root, row, manifest):
    name = row.get("receipt")
    if not isinstance(name, str) or not _RECEIPT.fullmatch(name):
        raise LineageVerificationError("unsafe receipt filename")
    path = _inside(Path(root) / name, root)
    cycle.verify(path, row.get("receipt_sha256"))
    receipt = cycle.json(path)
    request = receipt.get("request")
    if (not isinstance(request, dict) or receipt.get("ordinal") != row.get("ordinal")
        or receipt.get("label") != row.get("label")
        or receipt.get("request_sha256") != digest(request)
        or receipt.get("source_binding_sha256") != digest(manifest)
        or receipt.get("token_reservation") != row.get("token_reservation")):
        raise LineageVerificationError("receipt/request/source identity differs")
    # Historical failure remains a failure. Native bytes and metadata are checked;
    # no ordinary body is converted into a tool response or an accepted document.
    evidence = receipt.get("call_evidence", {})
    directory = Path(evidence.get("directory", ""))
    if not directory.is_absolute(): directory = Path(root) / directory
    directory = _inside(directory, Path(root) / "call_evidence")
    identity = {"ordinal": receipt["ordinal"], "label": receipt["label"],
        "request_sha256": receipt["request_sha256"], "source_binding_sha256": receipt["source_binding_sha256"],
        "role": request["role"], "model": request["model"]}
    document = cycle.json(directory / "IDENTITY.json")
    if (document.get("identity") != identity or document.get("identity_sha256") != digest(identity)
        or evidence.get("identity_sha256") != digest(identity)):
        raise LineageVerificationError("native evidence identity differs")
    outbound = _outbound(cycle, project, directory, request, digest(identity))
    metadata = receipt.get("response_metadata", {})
    if metadata.get("response_body_complete") is True:
        body = cycle.json(directory / "RESPONSE_BODY_MANIFEST.json")
        raw_path = _inside(directory / body.get("body_file", ""), directory)
        raw = cycle.read_bytes(raw_path)
        raw_sha = cycle.sha(raw_path)
        if (body.get("identity_sha256") != digest(identity) or body.get("body_complete") is not True
            or body.get("stored_sha256") != raw_sha or body.get("original_sha256") != raw_sha
            or body.get("bytes") != len(raw) or body.get("original_bytes", len(raw)) != len(raw)
            or body.get("raw_bytes_preserved") is not True or body.get("credential_redacted") is not False
            or body.get("http_metadata", {}).get("http_status_code") != metadata.get("http_status_code")
            or metadata.get("raw_body_sha256") != raw_sha
            or strict_json(raw) != receipt.get("response_payload")):
            raise LineageVerificationError("native response body differs")
        total = metadata.get("total_tokens")
        if type(total) is int and strict_json(raw).get("usage", {}).get("total_tokens") != total:
            raise LineageVerificationError("native response usage differs")
        payload = strict_json(raw)
        if (metadata.get("requested_model") != request["model"] or metadata.get("response_model") != request["model"]
            or metadata.get("response_model") != payload.get("model")
            or metadata.get("response_id") != payload.get("id")
            or metadata.get("finish_reason") != payload.get("choices", [{}])[0].get("finish_reason")):
            raise LineageVerificationError("native model identity differs")
        if metadata.get("output_mode") == "tool_call":
            try:
                calls = payload["choices"][0]["message"]["tool_calls"]
                function = calls[0]["function"]
                if (len(calls) != 1 or function["name"] != outbound["tools"][0]["function"]["name"]
                    or function["arguments"] != receipt.get("response_text")
                    or (not _verified_invalid_json_failure(receipt)
                        and strict_json(function["arguments"]) != receipt.get("output"))):
                    raise LineageVerificationError("native tool arguments differ from receipt")
            except (KeyError, IndexError, TypeError) as exc:
                raise LineageVerificationError("native tool response incomplete") from exc
    return receipt


def _verified_invalid_json_failure(receipt):
    """Exact known605 protocol failure is consumption, never repaired native JSON."""
    try:
        meta=receipt["response_metadata"];payload=receipt["response_payload"];request=receipt["request"]
        choices=payload["choices"];calls=choices[0]["message"]["tool_calls"]
        arguments=calls[0]["function"]["arguments"];usage=payload["usage"];failure=receipt["failure"]
        if (receipt.get("ordinal")!=605 or receipt.get("label")!="goal_source_audit_01"
                or receipt.get("status")!="interface_rejected" or request.get("stage")!="goal_audit"
                or request.get("role")!="director" or request.get("model")!="deepseek-flash"
                or meta.get("http_status_code")!=200 or meta.get("response_body_complete") is not True
                or meta.get("finish_reason")!=choices[0].get("finish_reason")
                or meta.get("finish_reason")!="tool_calls" or len(choices)!=1 or len(calls)!=1
                or meta.get("output_mode")!="tool_call" or meta.get("strict_mode") is not False
                or meta.get("requested_model")!=meta.get("response_model") or meta.get("response_model")!=request["model"]
                or payload.get("model")!=request["model"] or meta.get("response_id")!=payload.get("id")
                or failure.get("code")!="INVALID_JSON_RESPONSE" or failure.get("category")!="interface"
                or failure.get("response_received") is not True or failure.get("blocks_handoff") is not True
                or failure.get("automatic_retry") is not False or receipt.get("automatic_retry") is not False
                or receipt.get("semantic_approval") is not False or receipt.get("output") is not None
                or receipt.get("validation") is not None or receipt.get("document_output") is not None
                or not receipt.get("completed_at") or arguments!=receipt.get("response_text")
                or not isinstance(arguments,str) or len(arguments)!=23896
                or hashlib.sha256(arguments.encode("utf8")).hexdigest()!="eb033bd54c0fd44631a2c11b73695cde5c23434dcb623a989807f15d1a3ded48"
                or meta.get("raw_body_sha256")!="b60408e22d2644df19203a8c9e3718e01d29a0648e9fa4ee31b7c4dd7eb13b2b"):
            return False
        for key in ("prompt_tokens","completion_tokens","total_tokens"):
            if type(usage.get(key)) is not int or type(meta.get(key)) is not int or usage[key]<0 or meta[key]!=usage[key]:return False
        if (usage["prompt_tokens"],usage["completion_tokens"],usage["total_tokens"])!=(27482,10784,38266):return False
        if usage["total_tokens"]!=usage["prompt_tokens"]+usage["completion_tokens"]:return False
        try:
            strict_json(arguments)
            return False
        except LineageVerificationError:
            pass
        # Parse solely to locate the original extra token. This local temporary
        # value is never returned, written, adopted or validated as a report.
        prefix,end=json.JSONDecoder().raw_decode(arguments)
        if type(prefix) is not dict or end!=23895 or arguments[end:]!="}":return False
        try:json.loads(arguments)
        except json.JSONDecodeError as exc:
            return exc.msg=="Extra data" and exc.pos==23895 and receipt.get("error")==str(exc)
        return False
    except (KeyError,IndexError,TypeError,ValueError):
        return False


def _verified_length_failure(receipt):
    """Accounting predicate after _receipt's exact native wire/body checks.

    The old task remains result_unknown/PENDING. This does not complete it,
    adopt its partial tool argument, or authorize re-dispatch of its identity.
    """
    metadata = receipt.get("response_metadata", {})
    failure = receipt.get("failure", {})
    payload = receipt.get("response_payload", {})
    choices = payload.get("choices")
    usage = payload.get("usage", {})
    model = receipt.get("request", {}).get("model")
    if (type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict
            or type(model) is not str or not model or type(usage) is not dict):
        return False
    if any(type(usage.get(key)) is not int or usage[key] < 0
           or type(metadata.get(key)) is not int or metadata[key] != usage[key]
           for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
        return False
    return (receipt.get("status") == "interface_rejected"
        and receipt.get("error") == "RESPONSE_TRUNCATED"
        and receipt.get("automatic_retry") is False and receipt.get("semantic_approval") is False
        and isinstance(receipt.get("completed_at"), str) and bool(receipt["completed_at"])
        and receipt.get("output") is None and receipt.get("document_output") is None
        and receipt.get("validation") is None
        and type(metadata.get("http_status_code")) is int and metadata["http_status_code"] == 200
        and metadata.get("response_body_complete") is True
        and metadata.get("finish_reason") == choices[0].get("finish_reason") == "length"
        and metadata.get("response_fault_code") == "RESPONSE_TRUNCATED"
        and metadata.get("output_mode") == "unusable_response"
        and metadata.get("requested_model") == metadata.get("response_model") == payload.get("model") == model
        and isinstance(payload.get("id"), str) and bool(payload["id"])
        and metadata.get("response_id") == payload["id"]
        and usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
        and failure.get("code") == failure.get("cause_code") == "RESPONSE_TRUNCATED"
        and failure.get("category") == "interface"
        and failure.get("response_received") is True and failure.get("provider_outcome_known") is True
        and failure.get("blocks_handoff") is True and failure.get("automatic_retry") is False
        and type(failure.get("http_status_code")) is int and failure["http_status_code"] == 200)


def _task_history(cycle, project, root, ledger):
    database = Path(root) / "TASKS.sqlite3"
    if not database.exists():
        raise LineageVerificationError("parent durable task history missing")
    for suffix in ("-wal", "-journal"):
        side = Path(str(database) + suffix)
        if side.exists():
            data = cycle.read_bytes(side)
            if data:
                raise LineageVerificationError("active SQLite journal; require certified existing read-only SQL guard")
    raw = cycle.read_bytes(database)
    if raw[:16] != b"SQLite format 3\x00":
        raise LineageVerificationError("complete SQLite task history required")
    # SQLite WAL-format main files can remain header version 2 after closure.
    # Normalize only the verified in-memory copy so deserialize never opens a
    # journal; original database bytes/SHA remain untouched and certificate-bound.
    memory = bytearray(raw)
    memory[18:20] = b"\x01\x01"
    try:
        with _RAW_SQL(":memory:") as connection:
            connection.deserialize(bytes(memory))
            columns = {row[1] for row in connection.execute("PRAGMA table_info(attempts)")}
            has_service_identity = {"service_task_id", "provider_id"}.issubset(columns)
            service_fields = "service_task_id,provider_id" if has_service_identity else "NULL,NULL"
            rows = connection.execute("SELECT graph_id,status,request,result,claim_id,request_sha,result_sha,"
                + service_fields + " FROM attempts ORDER BY rowid").fetchall()
    except sqlite3.Error as exc:
        raise LineageVerificationError("unreadable settled SQLite task history") from exc
    calls = ledger["calls"]
    scope = cycle.json(Path(root) / "USER_SCOPE.json")
    grant = scope.get("grant_id")
    if not isinstance(grant, str) or not grant:
        raise LineageVerificationError("durable task grant identity missing")
    if len(rows) != len(calls):
        raise LineageVerificationError("unreconciled new durable task claim")
    for data, row in zip(rows, calls):
        graph, status, request_text, result_text, claim_id, request_sha, result_sha, service_id, sql_provider = data
        receipt = _receipt(cycle, project, root, row, ledger["source_manifest"])
        if not result_text:
            raise LineageVerificationError("durable task result unknown; no redispatch")
        request, result = strict_json(request_text), strict_json(result_text)
        grant_key = "grant_id" if "fresh_legal_full_flow" in scope.get("schema", "") else "grant"
        expected_graph = "call_" + digest({grant_key: grant, "label": receipt["label"]})[:24]
        output = result.get("output", {})
        if "native_output" in output:
            ordinal_key = "receipt_ordinal" if "receipt_ordinal" in output else "ordinal"
            output_bound = output == {ordinal_key: receipt["ordinal"], "native_output": receipt.get("output")}
        else:
            output_bound = output.get("receipt_sha256") == digest(receipt)
        from scripts import run_fresh_legal_full_flow_v1 as original
        cycle.read_bytes(original.__file__)
        known, outcome, tool_status = original.classify_receipt(receipt)
        evidence = Path(receipt["call_evidence"]["directory"])
        if not evidence.is_absolute(): evidence = Path(root) / evidence
        native_raw = cycle.read_bytes(evidence / "response_body.raw")
        raw_result = result.get("raw_receipt", {})
        try:
            task_raw = base64.b64decode(raw_result.get("body", ""), validate=True)
        except (ValueError, TypeError) as exc:
            raise LineageVerificationError("durable task raw response incomplete") from exc
        # Preserve the old durable classification. The length exception proves
        # captured consumption only, not a completed/reusable task or document.
        if _verified_length_failure(receipt):
            history_bound = (not known and outcome == tool_status == "unknown"
                and has_service_identity and service_id is None and sql_provider == receipt["request"]["model"]
                and "service_task_id" in result and result["service_task_id"] is None
                and status == "result_unknown" and result.get("outcome") == "unknown"
                and result.get("result_known") is False and result.get("complete_end") is False
                and result.get("schema_tool_status") == "unknown"
                and "contract_valid" in result and result["contract_valid"] is None
                and result.get("output") == {"ordinal": receipt["ordinal"], "native_output": None})
        elif _verified_invalid_json_failure(receipt):
            history_bound=(known and outcome=="protocol_rejected" and tool_status=="rejected"
                and status=="protocol_rejected" and result.get("outcome")=="protocol_rejected"
                and result.get("result_known") is True and result.get("complete_end") is True
                and result.get("schema_tool_status")=="rejected" and result.get("contract_valid") is False
                and has_service_identity and service_id is None and sql_provider==receipt["request"]["model"]
                and "service_task_id" in result and result["service_task_id"] is None
                and result.get("output")=={"ordinal":605,"native_output":None})
        else:
            history_bound = (known and status == outcome and status == result.get("outcome")
                and result.get("result_known") is True and result.get("complete_end") is True
                and result.get("schema_tool_status") == tool_status)
        if (request != {"provider_id": receipt["request"]["model"], "payload": receipt["request"]}
            or graph != expected_graph or not history_bound
            or request_sha != digest(request) or result_sha != digest(result)
            or result.get("claim_id") != claim_id or result.get("request_sha256") != request_sha
            or result.get("usage_known") is not True or result.get("complete") is not True
            or result.get("usage") != {"unit": "reported_tokens", "amount": receipt["response_metadata"]["total_tokens"]}
            or not output_bound
            or raw_result.get("encoding") != "base64" or task_raw != native_raw
            or raw_result.get("sha256") != hashlib.sha256(native_raw).hexdigest()
            or raw_result.get("http_status") != receipt["response_metadata"]["http_status_code"]):
            raise LineageVerificationError("durable task/native receipt/cached identity differs")


def _expand_native_dependencies(cycle, project, observer):
    """Include ancestor native artifacts the old summary only referenced by SHA."""
    roots = sorted({str(Path(path).parent) for path in cycle._bytes
        if Path(path).name == "CALL_LEDGER.json" and "source_at_dispatch" not in Path(path).parts})
    native_roots = []
    for root in roots:
        ledger = cycle.json(Path(root) / "CALL_LEDGER.json")
        manifest = ledger.get("source_manifest")
        if not isinstance(manifest, dict):
            raise LineageVerificationError("unmapped ancestor ledger contract")
        for row in ledger.get("calls", []):
            receipt = cycle.json(Path(root) / row["receipt"])
            # Pre-evidence historical records are preserved by the successful
            # full legacy guard and the certificate SHA, never marked native.
            if receipt.get("call_evidence"):
                _receipt(cycle, project, root, row, manifest)
            else:
                raise LineageVerificationError("ancestor native evidence unavailable: " + str(root))
        if (Path(root) / "TASKS.sqlite3").exists():
            database = Path(root) / "TASKS.sqlite3"
            wal = Path(str(database) + "-wal")
            if wal.exists() and cycle.read_bytes(wal):
                # The old full guard already verifies this exact committed WAL
                # view via its original read-only SQLite query. Do not invent a
                # new checkpoint or rewrite/reconstruct the historical database.
                if _absolute(database) not in observer.sqlite_databases:
                    raise LineageVerificationError("nonempty ancestor WAL not certified by original SQL guard")
                cycle.read_bytes(database)
            else:
                _task_history(cycle, project, root, ledger)
        native_roots.append(root)
    return native_roots


def _parent_inherited(cycle, project, root):
    root = Path(root).resolve()
    ledger = cycle.json(root / "CALL_LEDGER.json")
    starting = ledger.get("starting_spend", {})
    for key in _INHERITED_KEYS[:-1]:
        if type(starting.get(key)) is not int or starting[key] < 0:
            raise LineageVerificationError("complete inherited counters required")
    pending = starting.get("pending_ordinals")
    if not isinstance(pending, list) or len(set(pending)) != len(pending) or any(type(x) is not int or x < 1 for x in pending):
        raise LineageVerificationError("historical pending identity required")
    if (ledger.get("max_total_tokens") is not None or ledger.get("automatic_retry") is not False
        or ledger.get("old_budget_reset") is not False or ledger.get("old_governance_migrated") is not False):
        raise LineageVerificationError("parent continuation authorization policy differs")
    cycle.verify(root / "AUTHORIZATION.json", ledger.get("authorization_sha256"))
    manifest = ledger.get("source_manifest")
    _bind_manifest(cycle, project, manifest)
    for rel, sha in manifest.items():
        snapshot = _inside(root / "source_at_dispatch" / rel, root / "source_at_dispatch")
        cycle.verify(snapshot, sha)
    calls = ledger.get("calls")
    if not isinstance(calls, list): raise LineageVerificationError("ledger calls must be an array")
    with _RAW_SCANDIR(root) as entries:
        actual = {entry.name for entry in entries if entry.name.startswith("call_") and entry.name.endswith(".json")}
    expected = {row.get("receipt") for row in calls}
    if len(expected) != len(calls) or actual != expected:
        raise LineageVerificationError("orphan/missing/duplicate parent receipt")
    total = known = reserved = 0
    seen = set()
    unknown = []
    for index, row in enumerate(calls):
        if type(row.get("ordinal")) is not int or row["ordinal"] != starting["calls_started"] + index + 1:
            raise LineageVerificationError("parent ledger ordinal differs")
        receipt = _receipt(cycle, project, root, row, manifest)
        metadata = receipt.get("response_metadata", {})
        usage = metadata.get("total_tokens")
        complete = (type(metadata.get("http_status_code")) is int and 200 <= metadata["http_status_code"] < 300
                    and metadata.get("response_body_complete") is True and metadata.get("finish_reason") in ("stop", "tool_calls")
                    and type(usage) is int and usage >= 0)
        if ((not complete and not _verified_length_failure(receipt))
                or receipt.get("status") not in ("contract_valid", "contract_rejected", "interface_rejected")):
            raise LineageVerificationError("parent has unresolved new dispatch; reconcile original identity")
        response_id = metadata.get("response_id")
        if response_id:
            if response_id in seen: raise LineageVerificationError("duplicate provider response identity")
            seen.add(response_id)
        total += usage
        known += 1
    inherited = {"calls_started": starting["calls_started"] + len(calls),
        "reported_tokens": starting["reported_tokens"] + total,
        "calls_with_known_usage": starting["calls_with_known_usage"] + known,
        "unknown_token_reservations": starting["unknown_token_reservations"] + reserved,
        "pending_ordinals": list(pending) + unknown}
    _task_history(cycle, project, root, ledger)
    return inherited, ledger


def _expected_inherited(value):
    if not isinstance(value, dict) or any(key not in value for key in _INHERITED_KEYS):
        raise LineageVerificationError("all expected inherited counters required")
    return {key: deepcopy(value[key]) for key in _INHERITED_KEYS}


def build_lineage_certificate(project, parent_root, *, certified_check: Callable[[], dict],
                             expected_summary: dict, dependency_paths: Iterable,
                             guard_code_paths: Iterable):
    """Run unchanged full read-only guard once and capture its entire actual I/O.

    Use an isolated prepare process: the temporary observer is process-wide. The
    supplied callback is the trusted existing full guard/summary, not a mock in
    production. All callback implementation files must also be explicitly bound.
    This function returns a document; the caller alone saves/freezes it.
    """
    project, parent_root = Path(project).resolve(), Path(parent_root).resolve()
    expected = {"calls_started": expected_summary.get("effective_calls_started"),
        "reported_tokens": expected_summary.get("effective_reported_tokens"),
        "calls_with_known_usage": expected_summary.get("effective_calls_with_known_usage"),
        "unknown_token_reservations": expected_summary.get("unknown_token_reservations"),
        "pending_ordinals": expected_summary.get("historical_pending_ordinals")}
    if any(expected[key] is None for key in _INHERITED_KEYS):
        raise LineageVerificationError("complete expected frozen parent summary required")
    code_paths = list(guard_code_paths)
    if not code_paths or not callable(certified_check):
        raise LineageVerificationError("complete existing guard implementation binding required")
    first = VerificationCycle()
    for path in list(dependency_paths) + code_paths:
        first.read_bytes(path)
    observer = _ReadObserver(first)
    with observer.activate():
        summary = certified_check()
    if not isinstance(summary, dict):
        raise LineageVerificationError("full guard must return its verified runtime summary")
    if summary != expected_summary:
        raise LineageVerificationError("full guard summary differs from frozen terminal parent")
    native_roots = _expand_native_dependencies(first, project, observer)
    for root in native_roots:
        observer.directories.setdefault(root, _inventory(root))
    inherited, ledger = _parent_inherited(first, project, parent_root)
    if inherited != expected:
        raise LineageVerificationError("parent accumulation differs from explicitly inherited spend")
    for key, expected_value in (("effective_calls_started", inherited["calls_started"]),
        ("effective_reported_tokens", inherited["reported_tokens"]),
        ("effective_calls_with_known_usage", inherited["calls_with_known_usage"])):
        if summary.get(key) != expected_value:
            raise LineageVerificationError("certified summary differs: " + key)
    if summary.get("old_budget_reset") is not False or summary.get("media_calls") != 0:
        raise LineageVerificationError("certified summary authorization differs")
    # Enumerate parent root even if the old guard only selected receipt filenames.
    observer.directories.setdefault(str(parent_root), _inventory(parent_root))
    files = {path: first.sha(path) for path in sorted(first._bytes)}
    directories = {path: members for path, members in sorted(observer.directories.items())}
    # Independent post-checkpoint epoch detects changes during old guard execution.
    stable = VerificationCycle()
    for path, sha in files.items(): stable.verify(path, sha)
    for path, members in directories.items():
        if _inventory(path) != members:
            raise LineageVerificationError("directory changed during checkpoint: " + path)
    for path, fact in observer.probes.items():
        if _probe_fact(path) != fact:
            raise LineageVerificationError("existence dependency changed during checkpoint: " + path)
    return {"schema": VERSION + "/certificate", "project": str(project), "parent_root": str(parent_root),
        "certified_by_existing_full_guard": True, "guard_code_paths": sorted(_absolute(p) for p in code_paths),
        "native_evidence_roots": native_roots,
        "files": files, "directories": directories, "sqlite_databases": sorted(observer.sqlite_databases),
        "existence_probes": deepcopy(observer.probes),
        "parent_ledger_sha256": first.sha(parent_root / "CALL_LEDGER.json"),
        "parent_model_configs_sha256": digest(ledger["model_configs"]),
        "inherited": inherited, "certified_summary": deepcopy(summary),
        "historical_unknown_preserved": True, "automatic_retry": False, "old_budget_reset": False,
        "media_calls_authorized": False, "permanent_hash_cache": False,
        "known_length_failure_consumption_only": True, "original_task_pending_identity_preserved": True,
        "known_invalid_json_consumption_only": True, "original_protocol_rejection_identity_preserved": True,
        "original_request_retry_authorized": False, "native_document_approval_from_certificate": False}


def verify_lineage_certificate(certificate_path, *, expected_certificate_sha256,
                              fresh_source_gate: Callable[[], object], expected_inherited=None):
    """New read-only SHA epoch; returns verified inherited facts, never a runtime."""
    cycle = VerificationCycle()
    if isinstance(certificate_path, dict):
        certificate = deepcopy(certificate_path)
        if digest(certificate) != expected_certificate_sha256:
            raise LineageVerificationError("certificate canonical SHA changed")
    else:
        cycle.verify(certificate_path, expected_certificate_sha256)
        certificate = cycle.json(certificate_path)
    if (certificate.get("schema") != VERSION + "/certificate"
        or certificate.get("certified_by_existing_full_guard") is not True
        or certificate.get("historical_unknown_preserved") is not True
        or certificate.get("automatic_retry") is not False or certificate.get("old_budget_reset") is not False
        or certificate.get("media_calls_authorized") is not False or certificate.get("permanent_hash_cache") is not False
        or certificate.get("known_invalid_json_consumption_only") is not True
        or certificate.get("original_protocol_rejection_identity_preserved") is not True
        or certificate.get("known_length_failure_consumption_only") is not True
        or certificate.get("original_task_pending_identity_preserved") is not True
        or certificate.get("original_request_retry_authorized") is not False
        or certificate.get("native_document_approval_from_certificate") is not False):
        raise LineageVerificationError("certificate policy differs")
    if not callable(fresh_source_gate):
        raise LineageVerificationError("fresh source/time gate required every epoch")
    files = certificate.get("files")
    if not isinstance(files, dict) or not files:
        raise LineageVerificationError("complete certified dependencies required")
    for path, sha in files.items():
        if not Path(path).is_absolute(): raise LineageVerificationError("absolute certified path required")
        cycle.verify(path, sha)
    for path, expected in certificate.get("directories", {}).items():
        if [list(item) for item in _inventory(path)] != expected:
            raise LineageVerificationError("new/missing ancestor file or claim: " + path)
    for path, expected in certificate.get("existence_probes", {}).items():
        if _probe_fact(path) != expected:
            raise LineageVerificationError("ancestor existence/type dependency changed: " + path)
    root = Path(certificate["parent_root"])
    if not root.is_absolute() or not Path(certificate["project"]).is_absolute():
        raise LineageVerificationError("absolute checkpoint roots required")
    inherited, ledger = _parent_inherited(cycle, certificate["project"], root)
    if (inherited != certificate.get("inherited")
        or (expected_inherited is not None and inherited != _expected_inherited(expected_inherited))
        or cycle.sha(root / "CALL_LEDGER.json") != certificate.get("parent_ledger_sha256")
        or digest(ledger["model_configs"]) != certificate.get("parent_model_configs_sha256")):
        raise LineageVerificationError("certified parent identity or inherited accumulation differs")
    # This dynamic check intentionally has no inherited runtime callback and is
    # never satisfied by the old checkpoint's successful source/time gate.
    source = fresh_source_gate()
    if not isinstance(source, dict) or not isinstance(source.get("blockers"), list) or source["blockers"]:
        raise LineageVerificationError("fresh source/time gate did not return a validated eligible packet")
    return {"schema": VERSION + "/verified_epoch", "inherited": inherited,
        "parent_ledger_sha256": certificate["parent_ledger_sha256"],
        "dependency_file_count": len(files), "file_read_counts": deepcopy(cycle.read_counts),
        "fresh_source_gate_result": source, "old_budget_reset": False, "media_calls": 0}
