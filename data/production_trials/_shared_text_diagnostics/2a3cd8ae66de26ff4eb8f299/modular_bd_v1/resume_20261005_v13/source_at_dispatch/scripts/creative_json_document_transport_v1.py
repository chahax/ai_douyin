"""Strict JSON-document tool envelope; independent, no provider calls or repairs.

The provider receives one string field. The original payload_json string is
preserved separately from its strictly parsed, schema-validated derived object.
An already parsed outer object cannot prove absence of lost duplicate outer keys;
use decode_envelope(raw_argument_text) to verify that part at the receive boundary.
"""
from copy import deepcopy
import hashlib
import json
import math
from jsonschema import Draft202012Validator
from src.content_factory.creative_workflow_contract import CreativeContractError

VERSION="creative_json_document_transport/v1"
TOOL_NAME="submit_creative_json"
RULES=("本次仅升级工具输出传输，原创作/审查任务和完整输入继续适用。"
       "此前要求直接输出内部字段的格式说明由本传输协议替代：只调用submit_creative_json，"
       "参数恰为payload_json一个字符串。该字符串是完整内部JSON对象的原文，"
       "按用户提供的inner_document_schema完整填写，数组仍为JSON数组；不要item包装、XML数组、"
       "代码围栏、patch或丢弃字段。JSON字符串中的引号和换行按JSON转义。"
       "思考或正文分析不能代替完整工具文档，不能仅返回摘要。")


class DocTransportError(CreativeContractError):
    def __init__(self,code,message,path=""):
        super().__init__(code+": "+message)
        self.code=code
        self.failure_kind="state_contract" if code=="JSON_DOCUMENT_INNER_SCHEMA_REJECTED" else "interface"
        self.detail={"code":code,"path":path,"automatic_retry":False,
                     "blocks_adoption":True,"semantic_approval":False,"failure_kind":self.failure_kind}


def fail(code,message,path=""):
    raise DocTransportError(code,message,path)


def _sha(value,scope="inner"):
    try:return hashlib.sha256(value.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:fail("JSON_DOCUMENT_"+scope.upper()+"_ENCODING_INVALID","原JSON字符串含非法UTF-8代理字符")


def _finite(value,path="",scope="inner"):
    prefix="JSON_DOCUMENT_"+scope.upper()+"_"
    if isinstance(value,float) and not math.isfinite(value):
        fail(prefix+"NONFINITE","JSON不得含非有限数字",path)
    if isinstance(value,dict):
        for key,item in value.items():
            if not isinstance(key,str):fail(prefix+"UNREPRESENTABLE","JSON字段名须为原string，不自动转换",path)
            _finite(item,path+"."+key if path else key,scope)
    elif isinstance(value,list):
        for index,item in enumerate(value):_finite(item,path+"."+str(index),scope)
    elif value is not None and type(value) not in (str,int,float,bool):
        fail(prefix+"UNREPRESENTABLE","只接受原JSON类型，不转换tuple/object",path)


def _loads(raw,scope="inner"):
    prefix="JSON_DOCUMENT_"+scope.upper()+"_"
    if not isinstance(raw,str):fail(prefix+"TEXT_REQUIRED","必须提供原始JSON字符串，不转换对象或数组")
    _sha(raw,scope)
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:fail(prefix+"DUPLICATE_KEY","JSON包含重复字段: "+key)
            result[key]=value
        return result
    def constant(value):fail(prefix+"NONFINITE","JSON不得含"+value)
    try:value=json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
    except json.JSONDecodeError as exc:
        fail(prefix+"INVALID_JSON","必须为完整唯一JSON，不移除围栏/XML、不拼接片段",str(exc.pos))
    _finite(value,scope=scope)
    return value

def _schema(inner_schema):
    if not isinstance(inner_schema,dict):fail("JSON_DOCUMENT_SCHEMA_INVALID","必须提供完整内部JSON Schema对象")
    try:Draft202012Validator.check_schema(inner_schema)
    except Exception as exc:fail("JSON_DOCUMENT_SCHEMA_INVALID",str(exc))
    return inner_schema


def _inner(payload,inner_schema):
    _schema(inner_schema)
    doc=_loads(payload)
    if not isinstance(doc,dict):fail("JSON_DOCUMENT_INNER_OBJECT_REQUIRED","内部文档必须为完整object，不接受顶层数组、null或JSON字符串")
    errors=list(Draft202012Validator(inner_schema).iter_errors(doc))
    if errors:
        error=errors[0]
        fail("JSON_DOCUMENT_INNER_SCHEMA_REJECTED",error.message,".".join(map(str,error.absolute_path)))
    return doc


def build_envelope_schema():
    return {"title":TOOL_NAME,"type":"object","additionalProperties":False,
            "required":["payload_json"],"properties":{"payload_json":{"type":"string","minLength":2,
            "description":"完整内部JSON对象原文，严格按用户inner_document_schema；仅此一个字符串字段"}}}


def build_tool():
    return {"type":"function","function":{"name":TOOL_NAME,
            "description":"提交完整创作文档的原JSON字符串，不提交字段补丁",
            "parameters":build_envelope_schema()}}


def build_messages(original_messages,inner_schema):
    _schema(inner_schema)
    if not isinstance(original_messages,list) or not original_messages or any(not isinstance(m,dict) for m in original_messages):
        fail("JSON_DOCUMENT_MESSAGES_INVALID","必须提供完整原messages列表")
    result=deepcopy(original_messages)
    result.append({"role":"system","content":RULES})
    try:schema_json=json.dumps({"transport":VERSION,"tool_name":TOOL_NAME,
                               "inner_document_schema":deepcopy(inner_schema)},ensure_ascii=False,
                               separators=(",",":"),allow_nan=False)
    except (TypeError,ValueError):fail("JSON_DOCUMENT_SCHEMA_INVALID","内部Schema必须可无损表示为有限JSON")
    result.append({"role":"user","content":schema_json})
    return result


def decode_envelope(raw_argument_text):
    """Strictly decode original outer tool argument text, including duplicate keys."""
    value=_loads(raw_argument_text,"outer")
    _outer_shape(value)
    return value


def _outer_shape(raw):
    errors=list(Draft202012Validator(build_envelope_schema()).iter_errors(raw))
    if errors:
        error=errors[0]
        fail("JSON_DOCUMENT_OUTER_ENVELOPE_REJECTED",error.message,".".join(map(str,error.absolute_path)))


def extract_original_inner(raw,inner_schema):
    """Return immutable-source metadata and a separately derived internal object.

    raw may be original outer argument text or a previously strict-parsed outer
    dict. For a dict, outer_duplicate_keys_verified is explicitly false because
    this function cannot recover duplicate keys an earlier parser discarded.
    No trimming, type conversions, placeholder filling, or historical repairs.
    """
    if isinstance(raw,str):
        envelope=decode_envelope(raw);outer_hash=_sha(raw,"outer");verified=True
    elif isinstance(raw,dict):
        _outer_shape(raw);envelope=raw;outer_hash=None;verified=False
    else:fail("JSON_DOCUMENT_OUTER_ENVELOPE_REJECTED","外层必须为原JSON文本或已解析object，禁止转换类型")
    payload=envelope["payload_json"]
    doc=_inner(payload,inner_schema)
    return {"schema":VERSION,"document":doc,"payload_json":payload,"payload_sha256":_sha(payload),
            "document_sha256":_sha(json.dumps(doc,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)),
            "metadata":{"tool_name":TOOL_NAME,"payload_json_sha256":_sha(payload),
                "payload_utf8_bytes":len(payload.encode("utf-8")),"outer_argument_sha256":outer_hash,
                "outer_duplicate_keys_verified":verified,"inner_duplicate_keys_verified":True,
                "inner_schema_validated":True,"inner_object_is_derived":True,
                "source_string_modified":False,"automatic_repair":False,"semantic_approval":False}}


def encode_envelope(inner_document,inner_schema):
    """Offline helper; a supplied original JSON string stays byte-identical inside.

    Dict input is explicitly serialized to a new JSON string and then validated;
    callers must not describe that generated string as an original provider receipt.
    """
    if isinstance(inner_document,str):payload=inner_document
    elif isinstance(inner_document,dict):
        _finite(inner_document)
        try:payload=json.dumps(inner_document,ensure_ascii=False,separators=(",",":"),allow_nan=False)
        except (TypeError,ValueError):fail("JSON_DOCUMENT_INNER_UNREPRESENTABLE","文档包含不可表示或非有限JSON值")
    else:fail("JSON_DOCUMENT_INNER_OBJECT_REQUIRED","编码器只接受完整JSON对象或原JSON字符串")
    _inner(payload,inner_schema)
    return json.dumps({"payload_json":payload},ensure_ascii=False,separators=(",",":"),allow_nan=False)

# Backward-readable alias; this file is a new, unfrozen candidate.
JsonDocumentTransportError=DocTransportError
