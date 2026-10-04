"""Offline continuation controls; no provider/network traffic."""
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest
from scripts.creative_resume_dispatch_v2 import ContinuationRuntime, read, write
from src.content_factory.creative_workflow_roles import RoleResult, RoleResponseError
from src.content_factory.creative_workflow_contract import CreativeContractError

@pytest.fixture
def case(tmp_path):
    project=tmp_path/'project';project.mkdir();source=project/'new.py';source.write_text('version=1\n')
    quota=project/'quota.json';write(quota,{'stop_condition':{'triggered':False},'task_status':'active'})
    models={'writer':{'model':'MiniMax-M3'},'director':{'model':'deepseek-flash'}}
    provider=SimpleNamespace(calls=[],handler=None)
    def call(*a,**kw):
        provider.calls.append((a,kw));return provider.handler(*a,**kw)
    root=project/'resume';lock=project/'shared'/'DISPATCH.lock'
    runtime=ContinuationRuntime(project,root,[source],{'calls_started':55,'reported_tokens':558395,'legacy_cap':500000},models,
        client_factory=lambda:SimpleNamespace(call=call),quota_state=quota,shared_lock=lock)
    runtime.prepare()
    return SimpleNamespace(r=runtime,root=root,source=source,quota=quota,provider=provider,lock=lock)

def wire(text='one',schema=None):
    return {'role':'writer','model':'MiniMax-M3','messages':[{'role':'user','content':text}],
        'structured_schema':schema,'parameters':{'temperature':.4,'thinking':'disabled','max_completion_tokens':32}}

def response(value=None,tokens=100,rid='fixture',finish='tool_calls',mode='tool_call'):
    m={'response_id':rid,'finish_reason':finish,'output_mode':mode}
    if tokens is not None:m['total_tokens']=tokens
    return RoleResult(json.dumps(value or {}),m,{'fixture_only':True})

def test_inherits_spend_without_rewriting_legacy_cap(case):
    s=case.r.summary();assert s['effective_calls_started']==55 and s['effective_reported_tokens']==558395
    assert s['max_total_tokens'] is None and not s['old_budget_reset']
    assert read(case.r.ledger)['starting_spend']['legacy_cap']==500000 and not case.provider.calls

def test_pending_receipt_and_shared_lock_exist_before_dispatch(case):
    def handler(*a,**kw):
        led=read(case.r.ledger);assert len(led['calls'])==1 and led['calls'][0]['ordinal']==56
        rec=read(case.root/led['calls'][0]['receipt']);assert rec['status']=='pending_response'
        assert rec['token_reservation']>32 and case.lock.is_file()
        return response()
    case.provider.handler=handler;r=case.r.dispatch('draft',wire(),lambda x:{'valid':True})
    assert r['status']=='contract_valid' and not case.lock.exists()
    assert case.r.summary()['effective_reported_tokens']==558495

def test_identical_wire_under_new_label_does_not_redispatch(case):
    case.provider.handler=lambda *a,**kw:response()
    r=case.r.dispatch('draft',wire(),lambda x:{})
    assert case.r.dispatch('renamed',deepcopy(wire()),lambda x:{})==r
    assert len(case.provider.calls)==1

def test_same_label_different_request_is_not_overwritten(case):
    case.provider.handler=lambda *a,**kw:response();case.r.dispatch('draft',wire(),lambda x:{})
    with pytest.raises(RuntimeError,match='another request'):case.r.dispatch('draft',wire('different'),lambda x:{})
    assert len(case.provider.calls)==1

def test_timeout_is_unknown_and_prevents_new_dispatch(case):
    def fail(*a,**kw):raise TimeoutError('outcome not received')
    case.provider.handler=fail;r=case.r.dispatch('draft',wire(),lambda x:{})
    assert r['status']=='outcome_unknown' and case.r.summary()['unknown_token_reservations']>0
    assert case.r.dispatch('cached',wire(),lambda x:{})==r
    with pytest.raises(RuntimeError,match='unknown outcome'):case.r.dispatch('next',wire('next'),lambda x:{})
    assert len(case.provider.calls)==1

@pytest.mark.parametrize('tokens',[None,-1,True])
def test_unusable_usage_is_not_zero_and_prevents_followup(case,tokens):
    case.provider.handler=lambda *a,**kw:response(tokens=tokens)
    case.r.dispatch('one',wire(),lambda x:{})
    with pytest.raises(RuntimeError,match='unknown outcome'):case.r.dispatch('next',wire('next'),lambda x:{})
    assert case.r.summary()['unknown_token_reservations']>0 and len(case.provider.calls)==1

def test_known_truncation_can_only_be_followed_by_distinct_explicit_request(case):
    case.provider.handler=lambda *a,**kw:response(finish='length')
    r=case.r.dispatch('review',wire(),lambda x:pytest.fail('partial must not be validated'))
    assert r['status']=='interface_rejected' and r['failure']['code']=='RESPONSE_TRUNCATED'
    assert case.r.dispatch('same',wire(),lambda x:{})==r
    case.provider.handler=lambda *a,**kw:response(rid='new')
    second=case.r.dispatch('review_v2',wire('corrected full protocol'),lambda x:{})
    assert second['status']=='contract_valid' and len(case.provider.calls)==2

def test_missing_required_tool_has_interface_branch(case):
    case.provider.handler=lambda *a,**kw:response(mode='content',finish='stop')
    r=case.r.dispatch('one',wire(schema={'type':'object'}),lambda x:pytest.fail('no tool'))
    assert r['status']=='interface_rejected' and r['failure']['code']=='REQUIRED_TOOL_MISSING'

def test_type_error_has_state_contract_branch(case):
    case.provider.handler=lambda *a,**kw:response({'beats':{'item':[]}})
    schema={'type':'object','properties':{'beats':{'type':'array'}},'required':['beats']}
    r=case.r.dispatch('one',wire(schema=schema),lambda x:{})
    assert r['status']=='contract_rejected' and r['failure']['category']=='state_contract'

def test_business_valueerror_is_not_invalid_json(case):
    case.provider.handler=lambda *a,**kw:response()
    def bad(value):raise CreativeContractError('MODULE_STATE: source mismatch')
    r=case.r.dispatch('one',wire(),bad)
    assert r['status']=='contract_rejected' and r['failure']['category']=='state_contract'

def test_source_or_receipt_mutation_blocks_dispatch(case):
    case.source.write_text('version=2\n')
    with pytest.raises(RuntimeError,match='source/model'):case.r.dispatch('one',wire(),lambda x:{})
    assert not case.provider.calls

def test_receipt_mutation_and_orphan_are_blocked(case):
    case.provider.handler=lambda *a,**kw:response();r=case.r.dispatch('one',wire(),lambda x:{})
    row=read(case.r.ledger)['calls'][0];write(case.root/row['receipt'],{**r,'status':'passed'})
    with pytest.raises(RuntimeError,match='receipt changed'):case.r.dispatch('next',wire('next'),lambda x:{})
    assert len(case.provider.calls)==1

def test_latched_quota_stop_is_enforced_before_pending_or_provider(case):
    write(case.quota,{'stop_condition':{'triggered':True},'task_status':'paused'})
    with pytest.raises(RuntimeError,match='stop is latched'):case.r.dispatch('one',wire(),lambda x:{})
    assert not read(case.r.ledger)['calls'] and not case.provider.calls

def test_existing_shared_lock_stops_all_dispatches(case):
    case.lock.parent.mkdir(exist_ok=True);case.lock.write_text('other dispatch')
    with pytest.raises(FileExistsError):case.r.dispatch('one',wire(),lambda x:{})
    assert not read(case.r.ledger)['calls'] and not case.provider.calls


def test_validator_cannot_rewrite_original_model_output(case):
    case.provider.handler=lambda *a,**kw:response({'text':'model original'})
    def mutate(value):
        value['text']='validator edited';return {'checked':True}
    r=case.r.dispatch('one',wire(),mutate)
    assert r['output']['text']=='model original'
    assert json.loads(r['response_text'])==r['output']
    assert case.r.dispatch('cached',wire(),mutate)['output']==r['output']
    assert len(case.provider.calls)==1


def test_cached_valid_response_is_checked_by_current_validator_without_rewrite(case):
    case.provider.handler=lambda *a,**kw:response({'text':'original'})
    r=case.r.dispatch('one',wire(),lambda x:{})
    row=read(case.r.ledger)['calls'][0];prior=(case.root/row['receipt']).read_bytes()
    def reject(value):raise CreativeContractError('MODULE_SOURCE: no longer current')
    cached=case.r.dispatch('different_label',wire(),reject)
    assert cached['status']=='contract_rejected' and cached['cached_response_rejected_locally']
    assert cached['output']==r['output'] and (case.root/row['receipt']).read_bytes()==prior
    assert len(case.provider.calls)==1


def test_four_digit_ordinal_remains_reusable_and_accounted(case):
    inherited=deepcopy(case.r.inherited);inherited['calls_started']=999
    r=ContinuationRuntime(case.r.project,case.r.project/'four_digits',[case.source],inherited,case.r.models,
        client_factory=case.r.client_factory,quota_state=case.quota,shared_lock=case.lock)
    r.prepare();case.provider.handler=lambda *a,**kw:response()
    receipt=r.dispatch('ordinal',wire(),lambda x:{})
    assert receipt['ordinal']==1000 and r.summary()['effective_calls_started']==1000
    assert r.dispatch('cached',wire(),lambda x:{})==receipt
    assert len(case.provider.calls)==1


from scripts import creative_json_document_transport_v1 as transport

INNER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["title", "beats"],
    "properties": {
        "title": {"type": "string"},
        "beats": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "steps"],
            "properties": {"id": {"type": "string"},
                           "steps": {"type": "array", "items": {"type": "string"}}},
        }},
    },
}
DOCUMENT = {"title": "完整原值", "beats": [
    {"id": "B1", "steps": ['中文原动作与"台词"、字面 </item>、换行\n及🙂均保留']},
]}


def document_wire(text="one"):
    messages = [{"role": "user", "content": text}]
    value = wire(text, transport.build_envelope_schema())
    value.update(output_transport=transport.VERSION,
                 inner_document_schema=deepcopy(INNER_SCHEMA),
                 messages=transport.build_messages(messages, INNER_SCHEMA))
    return value


def text_response(text, tokens=100, rid="document_fixture", finish="tool_calls", mode="tool_call"):
    metadata = {"response_id": rid, "finish_reason": finish, "output_mode": mode}
    if tokens is not None:
        metadata["total_tokens"] = tokens
    return RoleResult(text, metadata, {"fixture_only": True})


def envelope(payload):
    return json.dumps({"payload_json": payload}, ensure_ascii=False)


def test_document_receipt_preserves_outer_and_full_inner_under_mutating_validator(case):
    payload = json.dumps(DOCUMENT, ensure_ascii=False, indent=2) + "\n \t"
    outer = envelope(payload)
    case.provider.handler = lambda *a, **kw: text_response(outer)
    def mutate(value):
        assert value == DOCUMENT
        value["title"] = "validator changed"
        value["beats"][0]["steps"].append("validator invented")
        return {"checked": True}
    receipt = case.r.dispatch("document", document_wire(), mutate)
    assert receipt["status"] == "contract_valid"
    assert receipt["response_text"] == outer
    assert receipt["output"] == {"payload_json": payload}
    assert receipt["document_output"] == DOCUMENT
    assert receipt["document_transport_validation"]["original_wire_output_preserved"] is True
    assert receipt["document_transport_validation"]["model_document_repaired"] is False
    meta = receipt["document_transport_validation"]["metadata"]
    assert meta["outer_duplicate_keys_verified"] and meta["inner_duplicate_keys_verified"]
    assert meta["source_string_modified"] is False
    assert not receipt["semantic_approval"]
    sent = case.provider.calls[0][1]
    assert sent["structured_schema"] == transport.build_envelope_schema()
    assert set(sent["structured_schema"]["properties"]) == {"payload_json"}
    assert len(case.provider.calls) == 1


def test_cached_document_reacceptance_never_changes_receipt_or_redispatches(case):
    payload = json.dumps(DOCUMENT, ensure_ascii=False)
    case.provider.handler = lambda *a, **kw: text_response(envelope(payload))
    first = case.r.dispatch("document", document_wire(), lambda value: {"stage": "first"})
    row = read(case.r.ledger)["calls"][0]
    original_receipt = (case.root / row["receipt"]).read_bytes()
    original_ledger = case.r.ledger.read_bytes()
    def second(value):
        value["beats"] = []
        return {"stage": "current"}
    cached = case.r.dispatch("renamed", document_wire(), second)
    assert cached["validation"] == {"stage": "current"}
    assert cached["output"] == first["output"] and cached["document_output"] == DOCUMENT
    assert (case.root / row["receipt"]).read_bytes() == original_receipt
    assert case.r.ledger.read_bytes() == original_ledger
    assert len(case.provider.calls) == 1


def test_cached_document_business_rejection_is_local_without_rewrite(case):
    case.provider.handler = lambda *a, **kw: text_response(envelope(json.dumps(DOCUMENT, ensure_ascii=False)))
    original = case.r.dispatch("document", document_wire(), lambda value: {})
    row = read(case.r.ledger)["calls"][0]
    raw_bytes = (case.root / row["receipt"]).read_bytes()
    def reject(value):
        raise CreativeContractError("MODULE_SOURCE: no longer current")
    cached = case.r.dispatch("renamed", document_wire(), reject)
    assert cached["status"] == "contract_rejected" and cached["cached_response_rejected_locally"]
    assert cached["output"] == original["output"]
    assert cached["document_output"] == DOCUMENT
    assert (case.root / row["receipt"]).read_bytes() == raw_bytes
    assert len(case.provider.calls) == 1


@pytest.mark.parametrize("outer,code", [
    ('{"payload_json":"{}","payload_json":"{}"}', "INVALID_JSON_RESPONSE"),
    ('{"payload_json":"{}","extra":NaN}', "INVALID_JSON_RESPONSE"),
    ('{"payload_json":', "INVALID_JSON_RESPONSE"),
    ('[]', "INVALID_JSON_RESPONSE"),
    ('{"payload_json":{"title":"bad"}}', "JSON_DOCUMENT_OUTER_ENVELOPE_REJECTED"),
    ('{"payload_json":"{}", "extra":[]}', "JSON_DOCUMENT_OUTER_ENVELOPE_REJECTED"),
])
def test_outer_faults_are_interface_rejections_and_cached_without_retry(case, outer, code):
    case.provider.handler = lambda *a, **kw: text_response(outer)
    validate_calls = []
    receipt = case.r.dispatch("document", document_wire(), lambda value: validate_calls.append(True))
    assert receipt["status"] == "interface_rejected"
    assert receipt["failure"]["code"] == code
    assert receipt["failure"]["category"] == "interface"
    assert receipt["response_text"] == outer
    assert validate_calls == []
    assert case.r.dispatch("same_wire", document_wire(), lambda value: pytest.fail("never adopt")) == receipt
    assert len(case.provider.calls) == 1


@pytest.mark.parametrize("payload,code,category,status", [
    ('{"title":"a","title":"b","beats":[]}', "JSON_DOCUMENT_INNER_DUPLICATE_KEY", "interface", "interface_rejected"),
    ('{"title":"a","beats":[{"id":"B1","id":"B2","steps":[]}]}', "JSON_DOCUMENT_INNER_DUPLICATE_KEY", "interface", "interface_rejected"),
    ('{"title":"a","beats":[],"x":NaN}', "JSON_DOCUMENT_INNER_NONFINITE", "interface", "interface_rejected"),
    ('{"title":"a","beats":[],"x":1e400}', "JSON_DOCUMENT_INNER_NONFINITE", "interface", "interface_rejected"),
    ('{"title":', "JSON_DOCUMENT_INNER_INVALID_JSON", "interface", "interface_rejected"),
    ('[]', "JSON_DOCUMENT_INNER_OBJECT_REQUIRED", "interface", "interface_rejected"),
    ('{"title":"a","beats":{"item":[]}}', "JSON_DOCUMENT_INNER_SCHEMA_REJECTED", "state_contract", "contract_rejected"),
    ('{"title":"a","beats":[{"id":"B1","steps":{"item":[]}}]}', "JSON_DOCUMENT_INNER_SCHEMA_REJECTED", "state_contract", "contract_rejected"),
    ('{"title":"a"}', "JSON_DOCUMENT_INNER_SCHEMA_REJECTED", "state_contract", "contract_rejected"),
])
def test_inner_faults_are_classified_without_schema_repair_or_validator(case, payload, code, category, status):
    outer = envelope(payload)
    case.provider.handler = lambda *a, **kw: text_response(outer)
    receipt = case.r.dispatch("document", document_wire(), lambda value: pytest.fail("invalid inner must not reach business validation"))
    assert receipt["status"] == status
    assert receipt["failure"]["code"] == code and receipt["failure"]["category"] == category
    assert receipt["output"] == {"payload_json": payload}
    assert receipt["response_text"] == outer
    assert "document_output" not in receipt
    assert not receipt["automatic_retry"]
    assert case.r.dispatch("renamed", document_wire(), lambda value: pytest.fail("must not retry")) == receipt
    assert len(case.provider.calls) == 1


@pytest.mark.parametrize("finish,mode,code", [
    ("length", "content", "RESPONSE_TRUNCATED"),
    ("stop", "content", "REQUIRED_TOOL_MISSING"),
])
def test_document_tool_or_truncation_fault_precedes_inner_adoption(case, finish, mode, code):
    case.provider.handler = lambda *a, **kw: text_response('{"payload_json":', finish=finish, mode=mode)
    receipt = case.r.dispatch("document", document_wire(), lambda value: pytest.fail("partial not adoptable"))
    assert receipt["status"] == "interface_rejected" and receipt["failure"]["code"] == code
    assert "document_output" not in receipt
    assert case.r.dispatch("same_wire", document_wire(), lambda value: {}) == receipt
    assert len(case.provider.calls) == 1


def test_document_business_failure_preserves_original_inner_and_stays_state_contract(case):
    case.provider.handler = lambda *a, **kw: text_response(envelope(json.dumps(DOCUMENT, ensure_ascii=False)))
    def reject(value):
        value["title"] = "changed only local"
        raise CreativeContractError("MODULE_CAUSAL_SOURCE: complete draft needed")
    receipt = case.r.dispatch("document", document_wire(), reject)
    assert receipt["status"] == "contract_rejected"
    assert receipt["failure"]["category"] == "state_contract"
    assert receipt["document_output"] == DOCUMENT
    assert json.loads(receipt["output"]["payload_json"]) == DOCUMENT


def test_unknown_document_call_is_not_dispatched_again_and_blocks_followup(case):
    def timeout(*a, **kw):
        raise TimeoutError("unknown original outcome")
    case.provider.handler = timeout
    receipt = case.r.dispatch("document", document_wire(), lambda value: {})
    assert receipt["status"] == "outcome_unknown"
    assert case.r.dispatch("same_wire", document_wire(), lambda value: {}) == receipt
    with pytest.raises(RuntimeError, match="unknown outcome"):
        case.r.dispatch("next", document_wire("next"), lambda value: {})
    assert case.r.summary()["unknown_token_reservations"] > 0
    assert len(case.provider.calls) == 1


@pytest.mark.parametrize("tokens", [None, -1, True])
def test_missing_or_invalid_document_usage_never_becomes_zero(case, tokens):
    case.provider.handler = lambda *a, **kw: text_response(envelope(json.dumps(DOCUMENT)), tokens=tokens)
    case.r.dispatch("document", document_wire(), lambda value: {})
    with pytest.raises(RuntimeError, match="unknown outcome"):
        case.r.dispatch("next", document_wire("next"), lambda value: {})
    assert case.r.summary()["unknown_token_reservations"] > 0
    assert len(case.provider.calls) == 1


@pytest.mark.parametrize("change", ["wrong_outer_schema", "wrong_role", "unknown_transport", "missing_transport"])
def test_unverified_document_wire_is_blocked_before_pending_or_client(case, change):
    value = document_wire()
    if change == "wrong_outer_schema":
        value["structured_schema"]["additionalProperties"] = True
    elif change == "wrong_role":
        value.update(role="director", model="deepseek-flash")
    elif change == "unknown_transport":
        value["output_transport"] = "unknown"
    else:
        value.pop("output_transport")
    with pytest.raises(RuntimeError):
        case.r.dispatch("document", value, lambda doc: {})
    assert not read(case.r.ledger)["calls"]
    assert case.provider.calls == []


def test_outer_numeric_overflow_is_finalized_with_known_usage_hashes_and_cache(case):
    from scripts.creative_resume_dispatch_v2 import sha_file
    outer = '{"payload_json":"{}", "unrepresentable":1e400}'
    case.provider.handler = lambda *a, **kw: text_response(outer)
    receipt = case.r.dispatch("overflow", document_wire(), lambda doc: pytest.fail("overflow must not validate"))
    assert receipt["status"] == "interface_rejected"
    assert receipt["failure"]["code"] == "INVALID_JSON_RESPONSE"
    assert receipt["response_text"] == outer and "output" not in receipt
    assert "document_output" not in receipt
    ledger = read(case.r.ledger)
    row = ledger["calls"][0]
    assert row["receipt_sha256"] == sha_file(case.root / row["receipt"])
    assert read(case.root / row["receipt"]) == receipt
    summary = case.r.summary()
    assert summary["effective_reported_tokens"] == 558495
    assert summary["unknown_token_reservations"] == 0
    assert not list(case.root.glob("*.write_*"))
    receipt_bytes = (case.root / row["receipt"]).read_bytes()
    ledger_bytes = case.r.ledger.read_bytes()
    assert case.r.dispatch("same_overflow", document_wire(), lambda doc: {}) == receipt
    assert (case.root / row["receipt"]).read_bytes() == receipt_bytes
    assert case.r.ledger.read_bytes() == ledger_bytes
    assert len(case.provider.calls) == 1
