"""Pure read-only evidence guard; no TaskStore constructor or service call."""
import hashlib
import json
from pathlib import Path
import sqlite3

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def readonly_original_draft_sql_snapshot(root, *, grant_id, source_binding_sha256, require_exact_attempt_count=False):
    """Select only old prefix7+failed graph. Prepare requires total7; live allows valid appends."""
    root = Path(root).resolve()
    ledger = read(root / "CALL_LEDGER.json")
    prefix = ledger["calls"][:7]
    if [r["ordinal"] for r in prefix] != list(range(521, 528)) or digest(ledger["source_manifest"]) != source_binding_sha256:
        raise ValueError("original seven-call/source prefix differs")
    stop = read(root / "compact_continuation_01/TEXT_STATE.json")
    last = stop["events"][-1]
    path = (root / prefix[-1]["receipt"]).resolve()
    if path.parent != root:
        raise ValueError("original receipt escaped root")
    r527 = read(path)
    if (stop.get("status") != "halt_execution_unknown" or stop.get("failure", {}).get("type") != "TaskStoreError"
        or stop.get("versions") != {"theme": 2, "plan": 2, "draft": 3} or stop.get("source_binding_sha256") != source_binding_sha256
        or last.get("event") != "claim" or last.get("phase") != "draft" or last.get("label") != "fresh_draft_03"
        or last.get("request_sha256") != digest(r527["request"]) or r527.get("ordinal") != 527 or r527.get("label") != "fresh_draft_02"):
        raise ValueError("exact local third-draft stop differs")
    wrapper_sha = digest({"provider_id": r527["request"]["model"], "payload": r527["request"]})
    gid_for = lambda label: "call_" + digest({"grant_id": grant_id, "label": label})[:24]
    gid = gid_for("fresh_draft_03")
    fields = ["claim_id", "graph_id", "node_id", "revision", "request_sha", "status", "result_sha", "created"]
    select = "SELECT " + ",".join(fields) + " FROM attempts"
    with sqlite3.connect((root / "TASKS.sqlite3").as_uri() + "?mode=ro", uri=True) as con:
        if require_exact_attempt_count and con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] != 7:
            raise ValueError("prepare requires exactly seven attempts")
        graph = con.execute("SELECT graph_id,definition,sha,created FROM graphs WHERE graph_id=?", (gid,)).fetchone()
        nodes = con.execute("SELECT node_id,kind,dependencies,current_revision FROM nodes WHERE graph_id=? ORDER BY node_id", (gid,)).fetchall()
        revs = con.execute("SELECT node_id,revision,input,input_sha,status,output,output_sha,reason,created FROM revisions WHERE graph_id=? ORDER BY node_id,revision", (gid,)).fetchall()
        failed = con.execute(select + " WHERE graph_id=? ORDER BY rowid", (gid,)).fetchall()
        duplicate = con.execute(select + " WHERE request_sha=? ORDER BY rowid", (wrapper_sha,)).fetchall()
        prefix_attempts = []
        for r in prefix:
            rows = con.execute(select + " WHERE graph_id=? ORDER BY rowid", (gid_for(r["label"]),)).fetchall()
            if len(rows) != 1:
                raise ValueError("missing or extra original graph attempt")
            prefix_attempts.append(dict(zip(fields, rows[0])))
        indices = []
        for r in con.execute("PRAGMA index_list('attempts')").fetchall():
            quoted = r[1].replace('"', '""')
            indices.append({"name": r[1], "unique": bool(r[2]), "columns": [v[2] for v in con.execute('PRAGMA index_info("' + quoted + '")').fetchall()]})
        schema_row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='attempts'").fetchone()
    if graph is None or graph[2] != digest(json.loads(graph[1])):
        raise ValueError("failed graph definition/SHA differs")
    expected = {"schema_version": "creative_studio_dag/v1", "graph_id": gid, "nodes": [
        {"node_id": "source", "kind": "source", "input": {"frozen_source_sha256": source_binding_sha256, "request_sha256": last["request_sha256"]}, "depends_on": []},
        {"node_id": "result", "kind": "text", "input": {"label": "fresh_draft_03", "phase": "draft"}, "depends_on": ["source"]}]}
    by_node = {r[0]: r for r in revs}
    node_defs = {r[0]: r for r in nodes}
    source_input, result_input = expected["nodes"][0]["input"], expected["nodes"][1]["input"]
    source_row, result_row = by_node.get("source"), by_node.get("result")
    source_ready = (source_row is not None and json.loads(source_row[2]) == source_input
        and source_row[3] == digest(source_input) and source_row[5] is not None
        and json.loads(source_row[5]) == source_input and source_row[6] == digest(source_input))
    result_prepared = (result_row is not None and json.loads(result_row[2]) == result_input
        and result_row[3] == digest(result_input))
    expected_nodes = (len(nodes) == 2 and set(node_defs) == {"source", "result"}
        and node_defs["source"][1] == "source" and json.loads(node_defs["source"][2]) == [] and node_defs["source"][3] == 1
        and node_defs["result"][1] == "text" and json.loads(node_defs["result"][2]) == ["source"] and node_defs["result"][3] == 1)
    if (json.loads(graph[1]) != expected or len(revs) != 2 or set(by_node) != {"source", "result"}
        or not source_ready or not result_prepared or not expected_nodes
        or by_node["source"][1] != 1 or by_node["source"][4] != "source_ready"
        or by_node["result"][1] != 1 or by_node["result"][4] != "prepared"
        or by_node["result"][5] is not None or by_node["result"][6] is not None or failed or len(duplicate) != 1
        or dict(zip(fields, duplicate[0])) != prefix_attempts[-1]
        or not any(i["unique"] and i["columns"] == ["request_sha"] for i in indices) or schema_row is None):
        raise ValueError("known local duplicate SQL boundary differs")
    return {"schema": "known_local_draft_taskstore_readonly_snapshot/v1", "source_binding_sha256": source_binding_sha256,
        "failed_label": "fresh_draft_03", "logical_request_sha256": last["request_sha256"], "wrapped_request_sha256": wrapper_sha,
        "graph": dict(zip(["graph_id", "definition", "sha", "created"], graph)),
        "nodes": [dict(zip(["node_id", "kind", "dependencies", "current_revision"], r)) for r in nodes],
        "revisions": [dict(zip(["node_id", "revision", "input", "input_sha", "status", "output", "output_sha", "reason", "created"], r)) for r in revs],
        "failed_graph_attempts": [dict(zip(fields, r)) for r in failed],
        "duplicate_request_attempts": [dict(zip(fields, r)) for r in duplicate], "original_prefix_attempts": prefix_attempts,
        "attempts_unique_indices": sorted(indices, key=lambda v: v["name"]), "attempts_table_schema_sha256": digest(schema_row[0])}
