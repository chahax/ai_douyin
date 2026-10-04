"""Single-string transport tests; no model or historical-receipt restoration."""
from copy import deepcopy
import hashlib
import json
import pytest
from scripts import creative_json_document_transport_v1 as t
from scripts.creative_resume_dispatch_v1 import digest

SCHEMA={"type":"object","additionalProperties":False,
    "required":["viewer_emotional_arc","causal_events","quoted_text"],"properties":{
        "viewer_emotional_arc":{"type":"array","items":{"type":"array","items":{"type":"string"}}},
        "causal_events":{"type":"array","minItems":2,"items":{"type":"object","additionalProperties":False,
            "required":["id","cause","effects"],"properties":{"id":{"type":"string"},
                "cause":{"type":"string"},"effects":{"type":"array","items":{"type":"string"}}}}},
        "quoted_text":{"type":"string"}}}
DOC={"viewer_emotional_arc":[["不安","理解"],["停顿","释放"]],
     "causal_events":[{"id":"E1","cause":"先听见原句","effects":["人物回应","观众观察"]},
                      {"id":"E2","cause":"前一事件已发生","effects":["结尾主动承担"]}],
     "quoted_text":"原样 \"台词\" </item> <item index=\"0\"> & \n下一行，中文与emoji🙂"}


def outer(payload):return json.dumps({"payload_json":payload},ensure_ascii=False)


def test_valid_nested_document_roundtrip_and_exact_original_payload_hash():
    original=json.dumps(DOC,ensure_ascii=False,indent=2)+"\n \t"
    result=t.extract_original_inner(t.encode_envelope(original,SCHEMA),SCHEMA)
    assert result["document"]==DOC
    assert result["payload_json"]==original
    assert result["payload_sha256"]==hashlib.sha256(original.encode("utf-8")).hexdigest()
    assert result["document_sha256"]==digest(DOC)
    assert result["metadata"]["outer_duplicate_keys_verified"] is True
    assert result["metadata"]["source_string_modified"] is False
    assert result["metadata"]["automatic_repair"] is False
    assert result["metadata"]["semantic_approval"] is False


def test_quotes_xml_literals_and_escape_spellings_are_never_rewritten():
    original=json.dumps(DOC,ensure_ascii=True,separators=(",",":"))
    result=t.extract_original_inner(outer(original),SCHEMA)
    assert result["payload_json"]==original
    assert result["document"]["quoted_text"]==DOC["quoted_text"]
    assert "</item>" in result["payload_json"]
    assert "\\u" in result["payload_json"]
    assert "<item index=" in result["document"]["quoted_text"]


def test_parsed_outer_object_has_honest_duplicate_key_limit_and_is_not_mutated():
    envelope={"payload_json":json.dumps(DOC,ensure_ascii=False)};before=deepcopy(envelope)
    result=t.extract_original_inner(envelope,SCHEMA)
    assert envelope==before
    assert result["metadata"]["outer_duplicate_keys_verified"] is False
    assert result["metadata"]["outer_argument_sha256"] is None
    result["document"]["causal_events"][0]["cause"]="派生副本变化"
    assert envelope==before


def test_tool_exact_name_one_string_no_nested_argument_arrays():
    tool=t.build_tool();schema=tool["function"]["parameters"]
    assert tool["function"]["name"]=="submit_creative_json"
    assert set(schema["properties"])=={"payload_json"}
    assert schema["properties"]["payload_json"]["type"]=="string"
    assert "items" not in schema["properties"]["payload_json"]
    assert schema["required"]==["payload_json"]
    assert schema["additionalProperties"] is False


def test_messages_preserve_full_context_and_include_complete_inner_schema_as_user_input():
    messages=[{"role":"system","content":"旧内容规则"},
              {"role":"user","content":json.dumps({"reference_full_text":"完整参考", "feedback":"需完整新稿"},ensure_ascii=False)}]
    before=deepcopy(messages);before_schema=deepcopy(SCHEMA)
    result=t.build_messages(messages,SCHEMA)
    assert messages==before and SCHEMA==before_schema
    assert result[:len(messages)]==messages
    assert result[-1]["role"]=="user"
    assert json.loads(result[-1]["content"])["inner_document_schema"]==SCHEMA
    assert json.loads(result[-1]["content"])["tool_name"]==t.TOOL_NAME
    assert "此前要求直接输出内部字段" in result[-2]["content"]
    assert sum("完整参考" in m["content"] for m in result)==1


@pytest.mark.parametrize("doc",[
    {"viewer_emotional_arc":[["理解"]],"quoted_text":"缺causal_events"},
    {**DOC,"viewer_emotional_arc":{"item":[["理解"]]}},
    {**DOC,"viewer_emotional_arc":[[[["理解","</item>"]]]]},
    {**DOC,"item":{"id":"E8"}},
    {**DOC,"causal_events":[{"id":"E1","effects":[]},{"id":"E2","cause":"原因","effects":[]}]},
    {**DOC,"causal_events":DOC["causal_events"][:1]}])
def test_missing_boxed_extra_deeply_wrapped_or_incomplete_document_is_rejected(doc):
    with pytest.raises(t.DocTransportError) as error:t.extract_original_inner(outer(json.dumps(doc,ensure_ascii=False)),SCHEMA)
    assert error.value.code=="JSON_DOCUMENT_INNER_SCHEMA_REJECTED"
    assert error.value.failure_kind=="state_contract"


@pytest.mark.parametrize("raw,code",[
    ('{"payload_json":"{}","payload_json":"{}"}',"JSON_DOCUMENT_OUTER_DUPLICATE_KEY"),
    ('{"payload_json":"{}", "other":NaN}',"JSON_DOCUMENT_OUTER_NONFINITE"),
    ('```json\n{"payload_json":"{}"}\n```',"JSON_DOCUMENT_OUTER_INVALID_JSON"),
    ('{"payload_json":"{}"} {"payload_json":"{}"}',"JSON_DOCUMENT_OUTER_INVALID_JSON"),
    ('<item>{"payload_json":"{}"}</item>',"JSON_DOCUMENT_OUTER_INVALID_JSON"),
    ('{"payload_json": {"item":[]}}',"JSON_DOCUMENT_OUTER_ENVELOPE_REJECTED"),
    ('{"payload_json":"{}", "item":[]}',"JSON_DOCUMENT_OUTER_ENVELOPE_REJECTED")])
def test_outer_faults_are_not_generically_repaired(raw,code):
    with pytest.raises(t.DocTransportError) as error:t.extract_original_inner(raw,SCHEMA)
    assert error.value.code==code and error.value.failure_kind=="interface"


@pytest.mark.parametrize("payload,code",[
    ('{"x":1,"x":2}',"JSON_DOCUMENT_INNER_DUPLICATE_KEY"),
    ('{"nested":{"x":1,"x":2}}',"JSON_DOCUMENT_INNER_DUPLICATE_KEY"),
    ('{"x":NaN}',"JSON_DOCUMENT_INNER_NONFINITE"),
    ('{"x":Infinity}',"JSON_DOCUMENT_INNER_NONFINITE"),
    ('{"x":-Infinity}',"JSON_DOCUMENT_INNER_NONFINITE"),
    ('{"x":1e400}',"JSON_DOCUMENT_INNER_NONFINITE"),
    ('{"x":',"JSON_DOCUMENT_INNER_INVALID_JSON"),
    ('```json\n{}\n```',"JSON_DOCUMENT_INNER_INVALID_JSON"),
    ('{} </item>',"JSON_DOCUMENT_INNER_INVALID_JSON"),
    ('[]',"JSON_DOCUMENT_INNER_OBJECT_REQUIRED"),
    ('null',"JSON_DOCUMENT_INNER_OBJECT_REQUIRED"),
    ('"{}"',"JSON_DOCUMENT_INNER_OBJECT_REQUIRED")])
def test_inner_interface_errors_are_rejected_before_schema_without_casting(payload,code):
    with pytest.raises(t.DocTransportError) as error:t.extract_original_inner(outer(payload),{"type":"object"})
    assert error.value.code==code and error.value.failure_kind=="interface"


@pytest.mark.parametrize("document",[{"x":float("nan")},{"x":(1,2)},{1:"int key"},[{}]])
def test_encoder_does_not_coerce_nonjson_or_wrong_top_level_types(document):
    with pytest.raises(t.DocTransportError):t.encode_envelope(document,{"type":"object"})


def test_dictionary_encoder_does_not_modify_source_document():
    before=deepcopy(DOC)
    assert t.extract_original_inner(t.encode_envelope(DOC,SCHEMA),SCHEMA)["document"]==DOC==before


def test_no_old_malformed_item_envelope_fallback():
    old={"viewer_emotional_arc":[[[["理解","</item>"]]]],"causal_events":{"item":{"id":"E1"}},"item":{"id":"E8"}}
    before=deepcopy(old)
    with pytest.raises(t.DocTransportError,match="JSON_DOCUMENT_OUTER_ENVELOPE_REJECTED"):
        t.extract_original_inner(old,SCHEMA)
    assert old==before
