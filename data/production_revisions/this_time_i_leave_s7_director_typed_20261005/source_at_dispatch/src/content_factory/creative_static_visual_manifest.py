"""Versioned persistent visual identity; poses and actions belong to shots only."""
import json
from copy import deepcopy
from .creative_workflow_contract import CreativeContractError

VERSION = 'static_visual_manifest_v1'
RULES = '''为完整剧本创建一次可跨镜复用的静态视觉清单，返回JSON，不写剧本或分镜。这里只锁定人物身份外观、物体形状和固定场景几何，绝不写站坐、手持、视线、表情、肩部紧松、动作、对白、某拍限定。道具owner_id是归属而不是当前拿在手里。clothing只写服装款式材质颜色，包作为prop；当前佩戴方式、位置由分镜首态决定。scene.relations仅描述固定场景元素关系，不能包含人物/移动道具。不要继承旧style中混入的姿态。所有外观是可复用制作选择，符合creative_brief和剧本，人物必须覆盖全体具名角色。render.style_option_id引用已选风格。所有自由文本仅写字段对应的静态属性，未知可作一致的制作选择。
契约：{"schema":"static_visual_manifest_v1","render":{"style_option_id":"S01","visual_medium":"...","palette":"...","light_source":"..."},"characters":[{"id":"C01","name":"...","age_group":"成年","hair":"发型颜色","clothing":"款式材质颜色","body_shape":"体型比例"}],"props":[{"id":"P01","name":"...","appearance":"形状材质颜色","owner_id":"C01或shared"}],"scene":{"name":"...","elements":[{"id":"E01","name":"...","appearance":"形状材质颜色"}],"relations":[{"subject":"E01","relation":"left_of|right_of|behind|in_front_of|next_to|above|below|inside","reference":"E02"}]}}
不输出其他键。'''

VERSION_V2 = 'static_visual_manifest_v2'
RELATIONS_V1 = {'left_of','right_of','behind','in_front_of','next_to','above','below','inside'}
RELATIONS_V2 = RELATIONS_V1 | {'on'}
RULES_V2 = RULES.replace(VERSION, VERSION_V2).replace('above|below|inside', 'above|below|inside|on') + "\n资产分类遵守creative_brief：明确为固定场景资产的桌椅、灯具等必须放scene.elements，不能因物理上能移动就放props；需要承接人物坐下的固定椅子须在scene.relations中绑定到对应桌边。props仅放剧情中的移动/随身物品。on表示接触并位于参照物表面，above仅指空间高于、不表示接触；关系值只能使用契约枚举，不能自行改为on_top_of。空间使用场景坐标，不把画面左右作为跨机位恒定关系。"


def build_static_manifest_prompt(context=None):
    return RULES_V2 if (context or {}).get('static_manifest_version') == VERSION_V2 else RULES


def build_static_manifest_repair(error, original_request, invalid_response):
    contract = build_static_manifest_prompt(original_request)
    instruction = ("修复静态视觉清单的目标对象，不是修复请求信封。只输出目标schema的完整JSON，"
                   "根字段严格为schema/render/characters/props/scene。保持正确的身份、外观与归属，修复指出的问题。"
                   "不得输出error、original_request、invalid_response、source_evidence、source_context或patches。"
                   "以下是原阶段完整契约，必须遵守：\n" + contract)
    return instruction, {'error': error, 'original_request': original_request,
                         'invalid_response': invalid_response, 'target_contract': contract}


def _keys(value, expected, path):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise CreativeContractError(f'{path} 字段必须为 {expected}')

def _text(value, path):
    if not isinstance(value, str) or not value.strip():
        raise CreativeContractError(f'{path} 必须为非空字符串')

def validate_static_manifest(value):
    _keys(value, 'schema render characters props scene', 'manifest')
    if value['schema'] not in (VERSION, VERSION_V2):
        raise CreativeContractError('静态视觉清单版本错误')
    _keys(value['render'], 'style_option_id visual_medium palette light_source', 'render')
    for k,v in value['render'].items(): _text(v, 'render.'+k)
    ids = set()
    for collection, keys in [('characters','id name age_group hair clothing body_shape'), ('props','id name appearance owner_id')]:
        entries = value[collection]
        if not isinstance(entries,list) or (collection == 'characters' and not entries):
            raise CreativeContractError(f'{collection} 必须为列表且人物不能为空')
        names = set()
        for row in entries:
            _keys(row, keys, collection)
            for k,v in row.items(): _text(v, collection+'.'+k)
            if row['id'] in ids or row['name'] in names:
                raise CreativeContractError('静态资产ID/集合内名称必须唯一')
            ids.add(row['id']); names.add(row['name'])
    characters = {c['id'] for c in value['characters']}
    if any(p['owner_id'] not in characters | {'shared'} for p in value['props']):
        raise CreativeContractError('道具归属必须引用人物ID或shared')
    scene = value['scene']
    _keys(scene, 'name elements relations', 'scene'); _text(scene['name'],'scene.name')
    if not isinstance(scene['elements'],list) or not scene['elements'] or not isinstance(scene['relations'],list):
        raise CreativeContractError('场景必须有固定元素列表及关系列表')
    elements = set()
    for row in scene['elements']:
        _keys(row, 'id name appearance', 'scene.elements')
        for k,v in row.items(): _text(v,'scene.elements.'+k)
        if row['id'] in ids: raise CreativeContractError('静态资产ID必须唯一')
        ids.add(row['id']); elements.add(row['id'])
    for index, row in enumerate(scene['relations']):
        _keys(row,'subject relation reference','scene.relations')
        if row['subject'] not in elements or row['reference'] not in elements or row['subject'] == row['reference']:
            raise CreativeContractError('固定空间关系只能引用两个不同固定元素，禁止人物和移动道具')
        allowed = RELATIONS_V2 if value['schema'] == VERSION_V2 else RELATIONS_V1
        if row['relation'] not in allowed:
            raise CreativeContractError(f"scene.relations.{index}.relation={row['relation']!r} 不合法；允许值：{', '.join(sorted(allowed))}")

def style_from_manifest(value):
    validate_static_manifest(value)
    style = deepcopy(value['render'])
    style['character_lock'] = f"确定{len(value['characters'])}名人物的静态身份外观：" + json.dumps(value['characters'],ensure_ascii=False,sort_keys=True)
    style['spatial_layout'] = json.dumps(value['scene'],ensure_ascii=False,sort_keys=True)
    return style
