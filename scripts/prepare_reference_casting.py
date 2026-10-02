"""Author production appearance/voice settings from an approved reference plan."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.test_director_pipeline import author_stage
from scripts.plan_reference_video import build_plan
from scripts.run_reference_director import check,digest

if __name__=='__main__':
    run=Path(sys.argv[1]).resolve();folder=run/sys.argv[2]
    plan=build_plan(run)
    prompt='''你是生活短片造型与声音导演。只输出合法JSON，不写剧情，不改站位、门向或动作。
为已审父女归家戏确定跨段一致的外貌、衣着、声线。父亲约60岁，女儿约28岁，两人双手空闲，不戴包、不持物。真实普通家庭人物，避免美颜网红脸和夸张哭相。情绪依靠之后的表演变化。
格式：{"characters":{"A":{"name":"父亲","appearance":"年龄、脸型、头发、固定衣着，60字以内","voice":"音色、音高、口音、语速基线，40字以内"},"B":{"name":"女儿","appearance":"","voice":""}},"lighting":"沿用室内玄关与门外走廊现有光源，脸部曝光可辨，50字以内","opening_expression":{"A":"开场尚未说话的状态，20字以内","B":"开场尚未被刺话影响的状态，20字以内"}}
这些仅是固定制作设定候选，不宣称生成视频或通过审核。'''
    value=author_stage(folder,prompt,{'space':plan['space'],'opening':plan['segments'][0]['performance'],'source_plan_sha256':digest(run/'delivery/execution_plan.json')},'reference_casting',temperature=0.5)
    check(set(value['characters'])=={'A','B'},'Two characters')
    check(all(all(isinstance(c.get(k),str) and c[k].strip() for k in ('name','appearance','voice')) for c in value['characters'].values()),'Incomplete casting')
    (folder/'validation.json').write_text(json.dumps({'status':'structure_valid_semantics_pending','media_approved':False},ensure_ascii=False,indent=2),encoding='utf-8')
    print(folder/'candidate.json')
