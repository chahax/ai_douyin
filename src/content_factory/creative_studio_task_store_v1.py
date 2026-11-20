"""Persistent, offline-only execution graph. This module never dispatches.

Public API (all returned values are detached JSON objects):
  TaskStore(db_path, *, fault_hook=None)
  register_graph(graph), register_authorization(authorization)
  snapshot(graph_id), node_history(graph_id, node_id)
  claim(graph_id, node_id, request, authorization, *, expected_revision=None)
  record_submission(claim_id, service_task_id, receipt)
  mark_unknown(claim_id, receipt, reason)
  accept_result(claim_id, result), recover(graph_id)
  revise_node(graph_id, node_id, new_input, authorization, *, expected_revision=None)

Graph: creative_studio_dag/v1; graph_id, nodes[{node_id, kind, input,
depends_on}], optional provenance. Kind: source/text/media/compile/review.
Sources are explicit imported inputs, never inferred or quality-approved.

Authorization: creative_studio_authorization/v1; authorization_id, graph_id,
node_ids, scope(source/text/media/offline), purpose(dispatch/revision),
source_sha256 (snapshot's current source hash), max_attempts, prior_attempts,
allows_content_revision, evidence_ref, evidence_sha256. It records an external
policy decision, NOT a grant created or verified by this database. No blanket
boolean authorization is accepted. Counts are immutable and never refunded.
Renaming a grant or graph does not reset the same external evidence's budget:
scope/purpose/evidence identity bind its maximum and inherited consumption.

Request: {provider_id: nonempty string, payload: JSON object}. Claim commits
BEFORE its caller may send. A crash after claim is conservatively unresolved;
the claim is never released or reissued. No dispatch-capable caller exists here.

Raw receipt: {encoding: utf-8/base64, body: string, sha256: bytes digest,
http_status: integer/null}. Complete results: creative_studio_result/v1 with
claim_id, request_sha256, service_task_id, outcome, result_known, usage_known,
usage, complete, complete_end, schema_tool_status, contract_valid, raw_receipt,
output. Outcome is completed/content_rejected/protocol_rejected/external_failed/
unknown; schema_tool_status is accepted/rejected/missing/unknown/not_applicable.
An HTTP-200 asynchronous failure additionally needs provider_task_state=failed
and its original service task ID; free-text "failed" is never inspected.
Usage is null or {unit: reported_tokens/credits/provider_units, amount: number}.
No free-text completion detection. Media completed output needs saved_files
[{path, sha256, size_bytes}], which are checked technically without viewing.

Only known, complete, schema-accepted TEXT content rejection can authorize a
new content revision. Source changes create invalidated downstream revisions,
but never cancel or erase original attempts, receipts, IDs or use. Any original
unresolved attempt still blocks another claim, even in a newer revision.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any
import uuid

VERSION = "creative_studio_task_store/v1"
GRAPH_SCHEMA = "creative_studio_dag/v1"
AUTH_SCHEMA = "creative_studio_authorization/v1"
RESULT_SCHEMA = "creative_studio_result/v1"
KINDS = {"source", "text", "media", "compile", "review"}
PENDING = {"claimed", "submitted", "result_unknown"}
READY = {"source_ready", "completed"}
TERMINAL = {"completed", "awaiting_human_review", "content_rejected", "protocol_rejected", "external_failed"}
SCOPE = {"source": "source", "text": "text", "review": "text", "media": "media", "compile": "offline"}
HEX = re.compile(r"^[0-9a-f]{64}$")


class TaskStoreError(ValueError):
    def __init__(self, code: str, message: str, detail: dict | None = None):
        self.code, self.detail = code, detail or {}
        super().__init__(message)


def _fail(code: str, message: str, **detail):
    raise TaskStoreError(code, message, detail)


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        _fail("INVALID_JSON", str(exc))


def _copy(value):
    return json.loads(_json(value))


def _sha(value) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        _fail("INVALID_FIELD", f"{name} must be a nonempty string")
    return value


def _digest(value, name):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        _fail("INVALID_FIELD", f"{name} must be a lowercase SHA256")
    return value


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        _fail("INVALID_FIELD", f"{name} must be an integer >= {minimum}")
    return value


def _fields(value, required, optional=()):
    if type(value) is not dict or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        _fail("INVALID_FIELDS", "Unexpected or missing contract fields", required=sorted(required))


def _receipt(value):
    _fields(value, {"encoding", "body", "sha256", "http_status"})
    if not isinstance(value["encoding"], str) or value["encoding"] not in {"utf-8", "base64"} or not isinstance(value["body"], str):
        _fail("INVALID_RECEIPT", "Raw receipt encoding/body is invalid")
    try:
        raw = value["body"].encode("utf-8") if value["encoding"] == "utf-8" else base64.b64decode(value["body"], validate=True)
    except (ValueError, UnicodeError) as exc:
        _fail("INVALID_RECEIPT", str(exc))
    if hashlib.sha256(raw).hexdigest() != _digest(value["sha256"], "receipt.sha256"):
        _fail("RECEIPT_SHA_MISMATCH", "Raw receipt byte identity differs")
    http = value["http_status"]
    if http is not None and (type(http) is not int or not 100 <= http <= 599):
        _fail("INVALID_RECEIPT", "HTTP status must be an integer 100..599 or null")
    return _copy(value)


def _now():
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    """One connection per short transaction; SQLite owns concurrency and crashes."""
    def __init__(self, db_path, *, fault_hook=None):
        if str(db_path) in {"", ":memory:"}:
            _fail("PERSISTENT_PATH_REQUIRED", "A dedicated persistent SQLite path is required")
        self.db_path = Path(db_path)
        self.fault_hook = fault_hook
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = self._connect()
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and "studio_meta" not in tables:
                _fail("FOREIGN_DATABASE", "Refusing to modify a non-studio database")
            if tables - {"studio_meta","graphs","nodes","revisions","authorizations","attempts","events"}:
                _fail("FOREIGN_DATABASE", "Refusing to mix this store with other database tables")
            if tables and con.execute("SELECT value FROM studio_meta WHERE key='version'").fetchone() != (VERSION,):
                _fail("DATABASE_VERSION_MISMATCH", "Studio database version is not supported")
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS studio_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS graphs (graph_id TEXT PRIMARY KEY, definition TEXT NOT NULL, sha TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS nodes (graph_id TEXT NOT NULL, node_id TEXT NOT NULL, kind TEXT NOT NULL, dependencies TEXT NOT NULL, current_revision INTEGER NOT NULL, PRIMARY KEY(graph_id,node_id), FOREIGN KEY(graph_id) REFERENCES graphs(graph_id));
                CREATE TABLE IF NOT EXISTS revisions (graph_id TEXT NOT NULL, node_id TEXT NOT NULL, revision INTEGER NOT NULL, input TEXT NOT NULL, input_sha TEXT NOT NULL, status TEXT NOT NULL, output TEXT, output_sha TEXT, reason TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(graph_id,node_id,revision), FOREIGN KEY(graph_id,node_id) REFERENCES nodes(graph_id,node_id));
                CREATE TABLE IF NOT EXISTS authorizations (authorization_id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, body TEXT NOT NULL, sha TEXT NOT NULL, FOREIGN KEY(graph_id) REFERENCES graphs(graph_id));
                CREATE TABLE IF NOT EXISTS attempts (claim_id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, node_id TEXT NOT NULL, revision INTEGER NOT NULL, attempt_index INTEGER NOT NULL, request TEXT NOT NULL, request_sha TEXT NOT NULL UNIQUE, identity_sha TEXT NOT NULL, authorization_id TEXT NOT NULL, provider_id TEXT NOT NULL, service_task_id TEXT, status TEXT NOT NULL, bindings TEXT NOT NULL, result TEXT, result_sha TEXT, created TEXT NOT NULL, UNIQUE(graph_id,node_id,revision), UNIQUE(provider_id,service_task_id), FOREIGN KEY(graph_id,node_id,revision) REFERENCES revisions(graph_id,node_id,revision), FOREIGN KEY(authorization_id) REFERENCES authorizations(authorization_id));
                CREATE TABLE IF NOT EXISTS events (event_id INTEGER PRIMARY KEY, claim_id TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, sha TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(claim_id,kind,sha), FOREIGN KEY(claim_id) REFERENCES attempts(claim_id));
            """)
            con.execute("INSERT OR IGNORE INTO studio_meta VALUES ('version',?)", (VERSION,))
            con.commit()
        except sqlite3.DatabaseError as exc:
            _fail("DATABASE_INVALID", str(exc))
        finally:
            con.close()

    def _connect(self):
        con = sqlite3.connect(str(self.db_path), timeout=30)
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=30000")
        return con

    def _fault(self, stage):
        if self.fault_hook is not None:
            self.fault_hook(stage)

    @contextmanager
    def _tx(self):
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            self._fault("before_commit")
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def _node(self, con, graph, node):
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT n.*,r.input,r.input_sha,r.status,r.output,r.output_sha,r.reason FROM nodes n JOIN revisions r ON r.graph_id=n.graph_id AND r.node_id=n.node_id AND r.revision=n.current_revision WHERE n.graph_id=? AND n.node_id=?", (graph,node)).fetchone()
        if row is None:
            _fail("NODE_NOT_FOUND", "Unknown graph/node", graph_id=graph, node_id=node)
        return dict(row)

    def _attempt(self, con, claim):
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM attempts WHERE claim_id=?", (claim,)).fetchone()
        if row is None:
            _fail("CLAIM_NOT_FOUND", "Unknown claim")
        result = dict(row)
        for key in ("request", "bindings", "result"):
            result[key] = json.loads(result[key]) if result[key] is not None else None
        result["request_sha256"] = result.pop("request_sha")
        result["identity_sha256"] = result.pop("identity_sha")
        return result

    def _source_sha(self, con, graph):
        rows = con.execute("SELECT n.node_id,r.input_sha FROM nodes n JOIN revisions r ON r.graph_id=n.graph_id AND r.node_id=n.node_id AND r.revision=n.current_revision WHERE n.graph_id=? AND n.kind='source' ORDER BY n.node_id", (graph,)).fetchall()
        return _sha({row[0]: row[1] for row in rows})

    def register_graph(self, graph):
        _fields(graph, {"schema_version", "graph_id", "nodes"}, {"provenance"})
        if graph["schema_version"] != GRAPH_SCHEMA or type(graph["nodes"]) is not list or not graph["nodes"]:
            _fail("INVALID_GRAPH", "Invalid graph schema or empty nodes")
        graph = _copy(graph)
        graph_id = _string(graph["graph_id"], "graph_id")
        if "provenance" in graph and type(graph["provenance"]) is not dict:
            _fail("INVALID_GRAPH", "provenance must be an object")
        nodes = {}
        for node in graph["nodes"]:
            _fields(node, {"node_id", "kind", "input", "depends_on"})
            nid = _string(node["node_id"], "node_id")
            if nid in nodes or not isinstance(node["kind"],str) or node["kind"] not in KINDS or type(node["input"]) is not dict or type(node["depends_on"]) is not list:
                _fail("INVALID_GRAPH", "Duplicate node or invalid node contract")
            deps = node["depends_on"]
            if any(not isinstance(d,str) or not d.strip() for d in deps) or len(set(deps)) != len(deps) or (node["kind"] == "source" and deps):
                _fail("INVALID_GRAPH", "Invalid dependencies")
            nodes[nid] = node
        visiting, visited = set(), set()
        def visit(nid):
            if nid not in nodes:
                _fail("INVALID_GRAPH", "Dependency not found", dependency=nid)
            if nid in visiting:
                _fail("GRAPH_CYCLE", "The dependency graph must be acyclic")
            if nid in visited:
                return
            visiting.add(nid)
            for parent in nodes[nid]["depends_on"]:
                visit(parent)
            visiting.remove(nid); visited.add(nid)
        for nid in nodes:
            visit(nid)
        with self._tx() as con:
            old = con.execute("SELECT sha FROM graphs WHERE graph_id=?", (graph_id,)).fetchone()
            if old:
                if old[0] != _sha(graph):
                    _fail("GRAPH_IDENTITY_CONFLICT", "Graph definition is immutable")
            else:
                con.execute("INSERT INTO graphs VALUES (?,?,?,?)", (graph_id,_json(graph),_sha(graph),_now()))
                for nid,node in nodes.items():
                    con.execute("INSERT INTO nodes VALUES (?,?,?,?,1)", (graph_id,nid,node["kind"],_json(node["depends_on"])))
                    out = node["input"] if node["kind"] == "source" else None
                    con.execute("INSERT INTO revisions VALUES (?,?,1,?,?,?,?,?,?,?)", (graph_id,nid,_json(node["input"]),_sha(node["input"]),"source_ready" if out is not None else "prepared",_json(out) if out is not None else None,_sha(out) if out is not None else None,"initial_import",_now()))
        return self.snapshot(graph_id)

    def _authorize(self, con, auth, graph, node=None, purpose=None):
        required = {"schema_version","authorization_id","graph_id","node_ids","scope","purpose","source_sha256","max_attempts","prior_attempts","allows_content_revision","evidence_ref","evidence_sha256"}
        _fields(auth, required)
        if auth["schema_version"] != AUTH_SCHEMA or auth["graph_id"] != graph:
            _fail("AUTHORIZATION_MISMATCH", "Authorization graph/schema differs")
        _string(auth["authorization_id"], "authorization_id")
        _string(auth["evidence_ref"], "evidence_ref")
        _digest(auth["evidence_sha256"], "evidence_sha256")
        _digest(auth["source_sha256"], "source_sha256")
        if auth["source_sha256"] != self._source_sha(con,graph):
            _fail("AUTHORIZATION_SOURCE_MISMATCH", "Authorization binds a different current source")
        if not isinstance(auth["scope"],str) or auth["scope"] not in {"source","text","media","offline"} or not isinstance(auth["purpose"],str) or auth["purpose"] not in {"dispatch","revision"} or type(auth["allows_content_revision"]) is not bool:
            _fail("INVALID_AUTHORIZATION", "Scope/purpose/revision flag is invalid")
        _integer(auth["max_attempts"], "max_attempts")
        _integer(auth["prior_attempts"], "prior_attempts")
        if auth["prior_attempts"] > auth["max_attempts"]:
            _fail("INVALID_AUTHORIZATION", "Prior use exceeds recorded maximum")
        ids = auth["node_ids"]
        if type(ids) is not list or not ids or any(not isinstance(x,str) or not x.strip() for x in ids) or len(set(ids)) != len(ids):
            _fail("INVALID_AUTHORIZATION", "node_ids must be distinct known nodes")
        for nid in ids:
            candidate = self._node(con,graph,nid)
            if SCOPE[candidate["kind"]] != auth["scope"]:
                _fail("AUTHORIZATION_SCOPE_MISMATCH", "Authorization scope differs from node kind")
        if node is not None and node not in ids or purpose is not None and auth["purpose"] != purpose:
            _fail("AUTHORIZATION_SCOPE_MISMATCH", "Authorization does not cover this operation")
        old = con.execute("SELECT sha FROM authorizations WHERE authorization_id=?", (auth["authorization_id"],)).fetchone()
        if old and old[0] != _sha(auth):
            _fail("AUTHORIZATION_IDENTITY_CONFLICT", "Existing authorization cannot be reset or enlarged")
        self._authorization_usage(con,auth)
        con.execute("INSERT OR IGNORE INTO authorizations VALUES (?,?,?,?)", (auth["authorization_id"],graph,_json(auth),_sha(auth)))
        used = self._authorization_usage(con,auth)
        return {"authorization":_copy(auth),"local_attempts":used,"remaining_attempts":auth["max_attempts"]-auth["prior_attempts"]-used,"grants_new_permission":False}

    def _authorization_usage(self, con, auth):
        key = tuple(auth[k] for k in ("scope","purpose","evidence_ref","evidence_sha256"))
        used = 0
        for row in con.execute("SELECT authorization_id,body FROM authorizations").fetchall():
            original = json.loads(row[1])
            if tuple(original[k] for k in ("scope","purpose","evidence_ref","evidence_sha256")) != key:
                continue
            if (original["max_attempts"],original["prior_attempts"]) != (auth["max_attempts"],auth["prior_attempts"]):
                _fail("AUTHORIZATION_SCOPE_BUDGET_CONFLICT", "Renaming an authorization cannot reset its evidence-bound budget")
            used += con.execute("SELECT COUNT(*) FROM attempts WHERE authorization_id=?", (row[0],)).fetchone()[0]
        return used

    def register_authorization(self, authorization):
        if type(authorization) is not dict:
            _fail("INVALID_AUTHORIZATION", "Authorization must be a contract object")
        with self._tx() as con:
            return self._authorize(con,authorization,authorization.get("graph_id"))

    def claim(self, graph_id, node_id, request, authorization, *, expected_revision=None):
        _fields(request, {"provider_id", "payload"})
        _string(request["provider_id"], "provider_id")
        if type(request["payload"]) is not dict:
            _fail("INVALID_REQUEST", "payload must be an object")
        request = _copy(request)
        with self._tx() as con:
            node = self._node(con,graph_id,node_id)
            if expected_revision is not None and (type(expected_revision) is not int or expected_revision != node["current_revision"]):
                _fail("REVISION_CONFLICT", "Caller revision is stale")
            if node["kind"] == "source" or node["status"] != "prepared":
                _fail("NODE_NOT_DISPATCHABLE", "Node is not a prepared executable revision", status=node["status"])
            if (node["kind"] == "compile") != (request["provider_id"] == "local_compiler"):
                _fail("PROVIDER_KIND_MISMATCH", "Only compile nodes may use the offline local_compiler provider")
            pending = con.execute("SELECT claim_id,status FROM attempts WHERE graph_id=? AND node_id=? AND status IN ('claimed','submitted','result_unknown')", (graph_id,node_id)).fetchall()
            if pending:
                _fail("ORIGINAL_ATTEMPT_UNRESOLVED", "Only reconcile the original attempt", claim_ids=[x[0] for x in pending])
            bindings = []
            for dep in json.loads(node["dependencies"]):
                parent = self._node(con,graph_id,dep)
                if parent["status"] not in READY or parent["output_sha"] is None:
                    _fail("DEPENDENCY_NOT_READY", "Dependency has no current valid output", dependency=dep,status=parent["status"])
                bindings.append({"node_id":dep,"revision":parent["current_revision"],"input_sha256":parent["input_sha"],"output_sha256":parent["output_sha"]})
            grant = self._authorize(con,authorization,graph_id,node_id,"dispatch")
            if grant["remaining_attempts"] <= 0:
                _fail("AUTHORIZATION_EXHAUSTED", "Recorded remaining capacity is zero", remaining_attempts=grant["remaining_attempts"])
            count = con.execute("SELECT COUNT(*) FROM attempts WHERE graph_id=? AND node_id=?", (graph_id,node_id)).fetchone()[0]
            cid = str(uuid.uuid4())
            identity = {"graph_id":graph_id,"node_id":node_id,"revision":node["current_revision"],"request_sha256":_sha(request),"source_sha256":self._source_sha(con,graph_id),"bindings":bindings}
            try:
                con.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?,NULL,'claimed',?,NULL,NULL,?)", (cid,graph_id,node_id,node["current_revision"],count+1,_json(request),_sha(request),_sha(identity),authorization["authorization_id"],request["provider_id"],_json(bindings),_now()))
            except sqlite3.IntegrityError:
                _fail("DUPLICATE_DISPATCH", "Revision/request already has an immutable claim")
            con.execute("UPDATE revisions SET status='claimed' WHERE graph_id=? AND node_id=? AND revision=?", (graph_id,node_id,node["current_revision"]))
            self._event(con,cid,"claim",identity)
            self._fault("after_claim_insert")
            return self._attempt(con,cid)

    def _event(self, con, claim, kind, body):
        con.execute("INSERT OR IGNORE INTO events(claim_id,kind,body,sha,created) VALUES (?,?,?,?,?)", (claim,kind,_json(body),_sha(body),_now()))

    def _bind_task_id(self, con, attempt, task_id):
        if task_id is None:
            return
        _string(task_id,"service_task_id")
        if attempt["service_task_id"] is not None and attempt["service_task_id"] != task_id:
            _fail("SERVICE_TASK_ID_CONFLICT", "Never substitute a new service task ID")
        try:
            con.execute("UPDATE attempts SET service_task_id=? WHERE claim_id=?", (task_id,attempt["claim_id"]))
        except sqlite3.IntegrityError:
            _fail("SERVICE_TASK_ALREADY_BOUND", "Service task belongs to another original claim")

    def record_submission(self, claim_id, service_task_id, receipt):
        receipt = _receipt(receipt)
        _string(service_task_id,"service_task_id")
        if receipt["http_status"] is None or not 200 <= receipt["http_status"] < 300:
            _fail("SUBMISSION_HTTP_NOT_ACCEPTED", "Known submission ID requires its successful original HTTP receipt")
        with self._tx() as con:
            attempt = self._attempt(con,claim_id)
            old = con.execute("SELECT body FROM events WHERE claim_id=? AND kind='submission'", (claim_id,)).fetchall()
            body = {"service_task_id":service_task_id,"raw_receipt":receipt}
            if old:
                if len(old) != 1 or json.loads(old[0][0]) != body:
                    _fail("SUBMISSION_RECEIPT_CONFLICT", "Original submission receipt is immutable")
                return attempt
            if attempt["status"] not in PENDING:
                _fail("TERMINAL_ATTEMPT", "Cannot resubmit a terminal original attempt")
            self._bind_task_id(con,attempt,service_task_id)
            self._event(con,claim_id,"submission",body)
            con.execute("UPDATE attempts SET status='submitted' WHERE claim_id=?", (claim_id,))
            self._update_revision(con,attempt,"submitted")
            self._fault("after_submission_record")
            return self._attempt(con,claim_id)

    def _update_revision(self, con, attempt, status, output=None):
        node = self._node(con,attempt["graph_id"],attempt["node_id"])
        if node["current_revision"] != attempt["revision"]:
            return False
        con.execute("UPDATE revisions SET status=?,output=?,output_sha=? WHERE graph_id=? AND node_id=? AND revision=?", (status,_json(output) if output is not None else None,_sha(output) if output is not None else None,attempt["graph_id"],attempt["node_id"],attempt["revision"]))
        return True

    def mark_unknown(self, claim_id, receipt, reason):
        receipt = _receipt(receipt)
        _string(reason,"reason")
        with self._tx() as con:
            attempt = self._attempt(con,claim_id)
            if attempt["status"] not in PENDING:
                _fail("TERMINAL_ATTEMPT", "A known terminal result cannot become unknown")
            self._event(con,claim_id,"unknown",{"reason":reason,"raw_receipt":receipt})
            con.execute("UPDATE attempts SET status='result_unknown' WHERE claim_id=?", (claim_id,))
            self._update_revision(con,attempt,"result_unknown")
            return self._attempt(con,claim_id)

    def _result(self, result, attempt, kind):
        required = {"schema_version","claim_id","request_sha256","service_task_id","outcome","result_known","usage_known","usage","complete","complete_end","schema_tool_status","contract_valid","raw_receipt","output"}
        _fields(result,required,{"provider_task_state"})
        if result["schema_version"] != RESULT_SCHEMA or result["claim_id"] != attempt["claim_id"] or result["request_sha256"] != attempt["request_sha256"]:
            _fail("RESULT_IDENTITY_MISMATCH", "Result must bind the exact original request/claim")
        if not isinstance(result["outcome"],str) or result["outcome"] not in {"completed","content_rejected","protocol_rejected","external_failed","unknown"} or not isinstance(result["schema_tool_status"],str) or result["schema_tool_status"] not in {"accepted","rejected","missing","unknown","not_applicable"}:
            _fail("INVALID_RESULT_STATUS", "Outcome/schema status must use exact contract enums")
        if "provider_task_state" in result and (result["provider_task_state"] != "failed" or result["outcome"] != "external_failed"):
            _fail("INVALID_RESULT_STATUS", "Explicit provider task failure metadata is invalid")
        for key in ("result_known","usage_known","complete","complete_end"):
            if type(result[key]) is not bool:
                _fail("INVALID_RESULT_FLAG", f"{key} must be a boolean")
        if result["contract_valid"] is not None and type(result["contract_valid"]) is not bool or result["output"] is not None and type(result["output"]) is not dict:
            _fail("INVALID_RESULT", "Contract/output field type is invalid")
        raw = _receipt(result["raw_receipt"])
        task_id = result["service_task_id"]
        if task_id is not None:
            _string(task_id,"service_task_id")
        if attempt["service_task_id"] is not None and task_id != attempt["service_task_id"]:
            _fail("SERVICE_TASK_ID_CONFLICT", "Result must retain the original service task ID")
        usage = result["usage"]
        if result["usage_known"]:
            _fields(usage,{"unit","amount"})
            amount = usage["amount"]
            if not isinstance(usage["unit"],str) or usage["unit"] not in {"reported_tokens","credits","provider_units"} or type(amount) not in {int,float} or type(amount) is float and not math.isfinite(amount) or amount < 0 or usage["unit"] == "reported_tokens" and type(amount) is not int:
                _fail("INVALID_USAGE", "Known usage must be a nonnegative number; tokens must be integer")
            if kind == "compile" and usage != {"unit":"provider_units","amount":0}:
                _fail("INVALID_USAGE", "Offline compilation has zero provider units")
        elif usage is not None:
            _fail("INVALID_USAGE", "Unknown usage must remain null")
        if kind == "compile" and (raw["http_status"] is not None or task_id is not None):
            _fail("INVALID_LOCAL_RESULT", "Offline compilation must not manufacture HTTP/service task evidence")
        if not result["result_known"] or not result["usage_known"] or result["outcome"] == "unknown":
            return "result_unknown", None
        if raw["http_status"] is None and kind != "compile":
            _fail("HTTP_EVIDENCE_MISSING", "Known service result needs original HTTP status")
        outcome = result["outcome"]
        if outcome in {"completed","content_rejected"}:
            if not result["complete"] or not result["complete_end"] or (kind != "compile" and not 200 <= raw["http_status"] < 300):
                _fail("RESULT_NOT_COMPLETE", "Success/content revision requires complete HTTP/termination evidence")
            expected_schema = "accepted" if kind in {"text","review"} else "not_applicable"
            if result["schema_tool_status"] != expected_schema:
                _fail("SCHEMA_TOOL_NOT_ACCEPTED", "Complete native contract must have the appropriate schema/tool evidence")
            if outcome == "content_rejected":
                if kind not in {"text","review"} or result["contract_valid"] is not False or result["output"] is None:
                    _fail("INVALID_CONTENT_REJECTION", "Only a complete native text rejection can be revised")
                return "content_rejected",None
            if result["contract_valid"] is not True or result["output"] is None:
                _fail("CONTRACT_NOT_ACCEPTED", "Completed output must have passed its local contract")
            if kind == "media":
                if not task_id:
                    _fail("MEDIA_TASK_ID_MISSING", "Saved media must retain original service task ID")
                files = result["output"].get("saved_files")
                if type(files) is not list or not files:
                    _fail("MEDIA_FILES_MISSING", "Saved media files are required")
                for file in files:
                    _fields(file,{"path","sha256","size_bytes"})
                    _string(file["path"],"saved_file.path")
                    _digest(file["sha256"],"saved_file.sha256")
                    _integer(file["size_bytes"],"saved_file.size_bytes",1)
                    path = Path(file["path"])
                    if not path.is_file() or path.stat().st_size != file["size_bytes"]:
                        _fail("MEDIA_FILE_INCOMPLETE", "Saved file does not match size evidence")
                    digest = hashlib.sha256()
                    with path.open("rb") as handle:
                        for chunk in iter(lambda:handle.read(1024*1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != file["sha256"]:
                        _fail("MEDIA_FILE_SHA_MISMATCH", "Saved file byte identity differs")
                return "awaiting_human_review",result["output"]
            return "completed",result["output"]
        if outcome == "external_failed" and raw["http_status"] is not None and raw["http_status"] < 400:
            if not task_id or result.get("provider_task_state") != "failed":
                _fail("INVALID_EXTERNAL_FAILURE", "HTTP-200 task failure needs structured failure metadata and original task ID")
        return outcome,None

    def accept_result(self, claim_id, result):
        result = _copy(result)
        usage_conflict = False
        with self._tx() as con:
            attempt = self._attempt(con,claim_id)
            node = self._node(con,attempt["graph_id"],attempt["node_id"])
            if attempt["result_sha"] == _sha(result):
                return {"attempt":attempt,"current_applied":node["current_revision"] == attempt["revision"],"late_result":node["current_revision"] != attempt["revision"],"idempotent":True}
            if attempt["status"] in TERMINAL:
                _fail("TERMINAL_RESULT_CONFLICT", "Known original result cannot be overwritten")
            status, output = self._result(result,attempt,node["kind"])
            if attempt["result"] and attempt["result"]["usage_known"] and (not result["usage_known"] or result["usage"] != attempt["result"]["usage"]):
                self._event(con,claim_id,"conflicting_result",result)
                usage_conflict = True
            else:
                self._bind_task_id(con,attempt,result["service_task_id"])
                self._event(con,claim_id,"result",result)
                con.execute("UPDATE attempts SET status=?,result=?,result_sha=? WHERE claim_id=?", (status,_json(result),_sha(result),claim_id))
                applied = self._update_revision(con,attempt,status,output)
                self._fault("after_result_record")
                return {"attempt":self._attempt(con,claim_id),"current_applied":applied,"late_result":not applied,"idempotent":False}
        if usage_conflict:
            _fail("KNOWN_USAGE_CONFLICT", "Previously known usage is immutable; conflicting receipt saved without overwriting original result")

    def revise_node(self, graph_id, node_id, new_input, authorization, *, expected_revision=None):
        if type(new_input) is not dict:
            _fail("INVALID_INPUT", "Revision input must be an object")
        new_input = _copy(new_input)
        with self._tx() as con:
            node = self._node(con,graph_id,node_id)
            if expected_revision is not None and (type(expected_revision) is not int or node["current_revision"] != expected_revision):
                _fail("REVISION_CONFLICT", "Revision changed")
            self._authorize(con,authorization,graph_id,node_id,"revision")
            if new_input == json.loads(node["input"]):
                _fail("UNCHANGED_REVISION", "Unchanged input cannot reset an attempt")
            if node["kind"] != "source":
                if node["status"] not in {"prepared","invalidated","content_rejected"}:
                    _fail("REVISION_NOT_ALLOWED", "Unknown/submitted/terminal outputs cannot be reset", status=node["status"])
                if node["status"] == "content_rejected" and not authorization["allows_content_revision"]:
                    _fail("CONTENT_REVISION_NOT_AUTHORIZED", "Known full-content revision needs explicit external authorization")
                pending = con.execute("SELECT claim_id FROM attempts WHERE graph_id=? AND node_id=? AND status IN ('claimed','submitted','result_unknown')", (graph_id,node_id)).fetchall()
                if pending:
                    _fail("ORIGINAL_ATTEMPT_UNRESOLVED", "Cannot revise around an unresolved original attempt")
            self._new_revision(con,node,new_input,"source_ready" if node["kind"] == "source" else "prepared","explicit_input_revision")
            descendants, frontier = set(), {node_id}
            all_nodes = con.execute("SELECT node_id,dependencies FROM nodes WHERE graph_id=?", (graph_id,)).fetchall()
            while frontier:
                following = {n for n,d in all_nodes if n not in descendants and n != node_id and set(json.loads(d)) & frontier}
                descendants.update(following); frontier = following
            for child_id in sorted(descendants):
                child = self._node(con,graph_id,child_id)
                self._new_revision(con,child,json.loads(child["input"]),"invalidated",f"upstream_revision:{node_id}")
            self._fault("after_revision_invalidation")
        return self.snapshot(graph_id)

    def _new_revision(self, con, node, payload, status, reason):
        rev = node["current_revision"]+1
        out = payload if status == "source_ready" else None
        con.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?,?,?)", (node["graph_id"],node["node_id"],rev,_json(payload),_sha(payload),status,_json(out) if out is not None else None,_sha(out) if out is not None else None,reason,_now()))
        con.execute("UPDATE nodes SET current_revision=? WHERE graph_id=? AND node_id=?", (rev,node["graph_id"],node["node_id"]))

    def snapshot(self, graph_id):
        con = self._connect()
        try:
            con.execute("BEGIN")
            row = con.execute("SELECT definition,sha FROM graphs WHERE graph_id=?", (graph_id,)).fetchone()
            if row is None:
                _fail("GRAPH_NOT_FOUND", "Graph does not exist")
            ids = [r[0] for r in con.execute("SELECT node_id FROM nodes WHERE graph_id=? ORDER BY node_id", (graph_id,))]
            nodes = []
            for nid in ids:
                node = self._node(con,graph_id,nid)
                for key in ("dependencies","input","output"):
                    node[key] = json.loads(node[key]) if node[key] is not None else None
                node["input_sha256"] = node.pop("input_sha"); node["output_sha256"] = node.pop("output_sha")
                nodes.append(node)
            claims = [r[0] for r in con.execute("SELECT claim_id FROM attempts WHERE graph_id=? ORDER BY created,claim_id", (graph_id,))]
            attempts = [self._attempt(con,c) for c in claims]
            grants = []
            for auth in con.execute("SELECT body FROM authorizations WHERE graph_id=? ORDER BY authorization_id", (graph_id,)).fetchall():
                body = json.loads(auth[0]); used = self._authorization_usage(con,body)
                grants.append({"authorization":body,"local_attempts":used,"remaining_attempts":body["max_attempts"]-body["prior_attempts"]-used,"grants_new_permission":False})
            usage = {}
            for attempt in attempts:
                result = attempt["result"]
                if result and result["usage_known"]:
                    unit,amount = result["usage"]["unit"],result["usage"]["amount"]
                    usage[unit] = usage.get(unit,0)+amount
            return {"schema_version":VERSION,"graph_id":graph_id,"graph_definition":json.loads(row[0]),"graph_sha256":row[1],"source_sha256":self._source_sha(con,graph_id),"nodes":nodes,"attempts":attempts,"authorizations":grants,"usage_totals":usage,"usage_unknown_claim_ids":[a["claim_id"] for a in attempts if not a["result"] or not a["result"]["usage_known"]],"grants_new_permission":False,"legacy_ledger_modified":False,"dispatch_performed":False}
        finally:
            con.close()

    def node_history(self, graph_id, node_id):
        con = self._connect()
        try:
            self._node(con,graph_id,node_id)
            revisions = []
            for row in con.execute("SELECT * FROM revisions WHERE graph_id=? AND node_id=? ORDER BY revision", (graph_id,node_id)).fetchall():
                value = dict(row)
                for key in ("input","output"):
                    value[key] = json.loads(value[key]) if value[key] is not None else None
                revisions.append(value)
            attempts = []
            for row in con.execute("SELECT claim_id FROM attempts WHERE graph_id=? AND node_id=? ORDER BY attempt_index", (graph_id,node_id)).fetchall():
                attempt = self._attempt(con,row[0])
                attempt["events"] = [{"kind":r[0],"body":json.loads(r[1]),"sha256":r[2],"created":r[3]} for r in con.execute("SELECT kind,body,sha,created FROM events WHERE claim_id=? ORDER BY event_id", (row[0],))]
                attempts.append(attempt)
            return {"graph_id":graph_id,"node_id":node_id,"revisions":revisions,"attempts":attempts}
        finally:
            con.close()

    def recover(self, graph_id):
        snapshot = self.snapshot(graph_id)
        actions = []
        for attempt in snapshot["attempts"]:
            status = attempt["status"]
            if status not in PENDING:
                continue
            result = attempt["result"]
            if attempt["service_task_id"]:
                action = "query_original_task"
            elif result and result["result_known"] and not result["usage_known"]:
                action = "stop_usage_unknown"
            elif status == "claimed":
                action = "stop_claim_unknown"
            else:
                action = "reconcile_unknown_without_task_id"
            actions.append({"claim_id":attempt["claim_id"],"provider_id":attempt["provider_id"],"service_task_id":attempt["service_task_id"],"request_sha256":attempt["request_sha256"],"revision":attempt["revision"],"action":action,"may_dispatch_new_request":False,"may_cancel_original_task":False})
        return {"schema_version":VERSION,"graph_id":graph_id,"actions":actions,"dispatch_performed":False,"grants_new_permission":False}
