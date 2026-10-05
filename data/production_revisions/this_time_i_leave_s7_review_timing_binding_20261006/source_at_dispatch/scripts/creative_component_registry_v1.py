"""Explicit component registration; no screenplay rewrite or provider calls.

A declaration splits an already evidenced collection into independent state
entities. It does not invent objects or decide natural-language story semantics.
"""
from copy import deepcopy
import hashlib
import json
import re

from src.content_factory.creative_workflow_contract import CreativeContractError

VERSION = "creative_component_registry_v1"


def _fail(message):
    raise CreativeContractError("component_registry: " + message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _text(value, path):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _fail(path + " 必须为非空且无边界空白的字符串")
    return value


def _keys(value, keys, path):
    if not isinstance(value, dict) or set(value) != set(keys):
        _fail(path + " 字段必须为 " + ",".join(keys))


def _count(evidence):
    match = re.fullmatch(r"([0-9]+|[一二三四五六七八九十]+)(张|个|件|枚|支|只|本|块)", evidence)
    if not match:
        _fail("source_count_evidence 必须是源中的明确数量词，例如三张")
    numeral = match.group(1)
    if numeral.isdigit():
        return int(numeral)
    digits = {c: i for i, c in enumerate("一二三四五六七八九", 1)}
    if numeral == "十":
        return 10
    if len(numeral) == 1 and numeral in digits:
        return digits[numeral]
    if numeral.count("十") == 1:
        left, right = numeral.split("十")
        if (not left or left in digits) and (not right or right in digits):
            return (digits.get(left, 1) * 10) + digits.get(right, 0)
    _fail("source_count_evidence 数量写法不支持")


def build_component_manifest(original_manifest, declarations, *, support_surface_ids):
    """Return a traceable bundle, with every collection replaced by its members.

    A member explicitly names source evidence, appearance and unchanged owner.
    The first source_evidence token is its unique literal member selector.
    Counts and evidence are checked literally, not inferred from screenplay prose.
    support_surface_ids is an explicit list of existing scene element IDs.
    """
    if not isinstance(original_manifest, dict):
        _fail("original_manifest 必须为对象")
    if not isinstance(declarations, list) or not declarations:
        _fail("缺少显式成员声明")
    original = deepcopy(original_manifest)
    props = original.get("props")
    characters = original.get("characters")
    elements = original.get("scene", {}).get("elements")
    if not isinstance(props, list) or not isinstance(characters, list) or not isinstance(elements, list):
        _fail("manifest人物、道具与固定元素必须为普通数组")
    all_entities = characters + props + elements
    all_ids = []
    for index, entity in enumerate(all_entities):
        if not isinstance(entity, dict):
            _fail(f"manifest实体{index}必须为对象")
        all_ids.append(_text(entity.get("id"), f"manifest实体{index}.id"))
    if len(all_ids) != len(set(all_ids)):
        _fail("manifest实体ID重复")
    char_ids = {x["id"] for x in characters}
    prop_by_id = {x["id"]: x for x in props}
    element_ids = {x["id"] for x in elements}
    if not isinstance(support_surface_ids, list) or not support_surface_ids:
        _fail("缺少显式支持面ID数组")
    for surface in support_surface_ids:
        _text(surface, "support_surface_ids")
        if surface not in element_ids:
            _fail("支持面不存在于原固定元素: " + surface)
    if len(support_surface_ids) != len(set(support_surface_ids)):
        _fail("支持面ID重复")
    replacements, collections, sources = {}, {}, {}
    occupied = set(all_ids)
    for di, declaration in enumerate(declarations):
        dp = f"declarations.{di}"
        _keys(declaration, ("source_prop_id", "source_count", "source_count_evidence", "members"), dp)
        source_id = _text(declaration["source_prop_id"], dp + ".source_prop_id")
        if source_id not in prop_by_id:
            _fail(dp + " source不存在于原props")
        if source_id in replacements:
            _fail(dp + " source重复声明")
        source = prop_by_id[source_id]
        owner = source.get("owner_id")
        if owner not in char_ids:
            _fail(dp + " 源owner未登记")
        count = declaration["source_count"]
        if type(count) is not int or count < 2:
            _fail(dp + " source_count必须为至少2的整数")
        evidence = _text(declaration["source_count_evidence"], dp + ".source_count_evidence")
        source_text = source.get("name", "") + "\n" + source.get("appearance", "")
        if evidence not in source_text or _count(evidence) != count:
            _fail(dp + " 数量证据与原集合不一致")
        members = declaration["members"]
        if not isinstance(members, list) or len(members) != count:
            _fail(dp + " 成员缺失或数量与源不一致")
        effective_members, selectors = [], set()
        for mi, member in enumerate(members):
            mp = f"{dp}.members.{mi}"
            _keys(member, ("id", "name", "appearance", "owner_id", "source_evidence"), mp)
            member_id = _text(member["id"], mp + ".id")
            if member_id in occupied:
                _fail(mp + " 成员ID重复或与原实体冲突")
            occupied.add(member_id)
            name = _text(member["name"], mp + ".name")
            appearance = _text(member["appearance"], mp + ".appearance")
            if member["owner_id"] != owner:
                _fail(mp + " 不允许改变owner")
            tokens = member["source_evidence"]
            if not isinstance(tokens, list) or not tokens:
                _fail(mp + " 缺少成员来源证据")
            for token in tokens:
                _text(token, mp + ".source_evidence")
                if token not in source_text or token not in name + "\n" + appearance:
                    _fail(mp + " 成员证据未被原登记或成员描述支持")
            if len(tokens) != len(set(tokens)):
                _fail(mp + " 成员证据重复")
            selector = tokens[0]  # first literal evidence identifies this distinct member
            if selector in selectors:
                _fail(mp + " 成员来源证据重复")
            selectors.add(selector)
            effective_members.append({"id": member_id, "name": name,
                "appearance": appearance, "owner_id": owner})
            sources[member_id] = {"source_prop_id": source_id,
                "source_prop_sha256": _digest(source), "source_evidence": deepcopy(tokens)}
        replacements[source_id] = effective_members
        collections[source_id] = {"member_ids": [m["id"] for m in effective_members],
            "source_count": count, "source_count_evidence": evidence,
            "source_prop_sha256": _digest(source)}
    effective = deepcopy(original)
    effective["props"] = [member for prop in props
        for member in replacements.get(prop["id"], [deepcopy(prop)])]
    effective["surface_ids"] = deepcopy(support_surface_ids)
    return {"schema": VERSION, "original_manifest": original,
        "original_manifest_sha256": _digest(original),
        "component_declarations": deepcopy(declarations),
        "component_declarations_sha256": _digest(declarations),
        "component_collections": collections, "member_source_map": sources,
        "effective_manifest": effective, "effective_manifest_sha256": _digest(effective),
        "semantic_approval": False, "production_ready": False}


def build_component_registry(original_manifest, declarations, support_surface_ids=None):
    """Public registry entry point; supporting surfaces must be explicit."""
    return build_component_manifest(original_manifest, declarations,
        support_surface_ids=support_surface_ids)


def validate_component_bundle(bundle):
    if not isinstance(bundle, dict) or bundle.get("schema") != VERSION:
        _fail("bundle schema错误")
    try:
        expected = build_component_manifest(bundle["original_manifest"],
            bundle["component_declarations"],
            support_surface_ids=bundle["effective_manifest"]["surface_ids"])
    except (KeyError, TypeError) as exc:
        _fail("bundle来源缺失: " + str(exc))
    if bundle != expected:
        _fail("bundle内容/映射/哈希不一致")
    return deepcopy(bundle["effective_manifest"])


def p03_member_declarations(original_manifest):
    """Explicit fixture for the original three named/color-coded notes."""
    prop = next((x for x in original_manifest.get("props", []) if x.get("id") == "P03"), None)
    if prop is None:
        _fail("P03原集合不存在")
    owner = prop.get("owner_id")
    return [{"source_prop_id": "P03", "source_count": 3,
        "source_count_evidence": "三张", "members": [
        {"id": "P03_Y", "name": "浅黄对账便利贴",
            "appearance": "正方形小纸片，浅黄底，深灰手写短词（对账）",
            "owner_id": owner, "source_evidence": ["浅黄", "对账"]},
        {"id": "P03_P", "name": "浅粉改明细便利贴",
            "appearance": "正方形小纸片，浅粉底，深灰手写短词（改明细）",
            "owner_id": owner, "source_evidence": ["浅粉", "改明细"]},
        {"id": "P03_B", "name": "浅蓝收尾便利贴",
            "appearance": "正方形小纸片，浅蓝底，深灰手写短词（收尾）",
            "owner_id": owner, "source_evidence": ["浅蓝", "收尾"]}]}]


def build_p03_registry(original_manifest):
    return build_component_manifest(original_manifest,
        p03_member_declarations(original_manifest), support_surface_ids=["E01", "E02"])
