"""Prepare one immutable full-series Seedance reference plan after the predecessor passes."""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def binding(path):
    path=Path(path).resolve()
    return {"path":str(path),"sha256":sha(path)}


def save(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("shot_id")
    parser.add_argument("--previous-run",required=True)
    parser.add_argument("--output-plan",required=True)
    args=parser.parse_args()

    run=ROOT/"data/video_generation/blank_cost_20260925/performance_revision_20260926"
    series=run/"photoreal_reference_v3"
    director=read(run/"director_execution_v6/candidate.json")
    shots={row["id"]:row for row in director["shots"]}
    shot=shots[args.shot_id]
    index=[row["id"] for row in director["shots"]].index(args.shot_id)
    if index==0:
        raise ValueError("use the reviewed S01 bootstrap plan")
    previous_id=director["shots"][index-1]["id"]
    previous=Path(args.previous_run).resolve()
    receipt=read(previous/"receipt.json")
    review=read(previous/"media_review.json")
    prior_plan=read(receipt["plan"])
    if prior_plan["shot_id"]!=previous_id or review.get("decision")!="visual_passed_audio_pending":
        raise ValueError("previous run is not the approved immediate predecessor")

    accepted_path=series/"ASSETS_ACCEPTED_FULL.json"
    accepted=read(accepted_path)
    by_id={row["asset_id"]:row for row in accepted["assets"]}
    number=int(args.shot_id[1:])
    if number<=8:
        ids=["CHENMO_THREE_VIEW","LINYU_THREE_VIEW_V3","FANGCHENG_THREE_VIEW","STUDIO_DAY_PHOTOREAL"]
    elif number<=10:
        ids=["CHENMO_THREE_VIEW","STUDIO_NIGHT_PHOTOREAL"]
    elif number<=15:
        ids=["CHENMO_THREE_VIEW","LINYU_THREE_VIEW_V3","FANGCHENG_THREE_VIEW","PROPERTY_FRONT_DESK_PHOTOREAL_V3"]
    else:
        ids=["CHENMO_THREE_VIEW","COURT_WINDOW_PHOTOREAL"]
    refs=[]
    for asset_id in ids:
        row=by_id[asset_id]
        refs.append({"asset_id":asset_id,"image":row["image"],"review":row["review"],"receipt":row["receipt"]})

    needs_video_ref = shot["cut_mode"]=="continuous" or args.shot_id in {"S11","S16"}
    directives=[]
    if needs_video_ref:
        directives.append("@video1是紧接上一段的已审核原始视频，只用于保持人物身份、服装、道具状态、空间方位和动作起点；从其尾态自然接续，不重复上一段动作。")
    labels={
      "CHENMO_THREE_VIEW":"只锁定陈默身份、短黑发、炭灰夹克和成年比例",
      "LINYU_THREE_VIEW_V3":"只锁定林屿身份、齐肩黑发、米白长袖开衫与橄榄绿无袖内搭",
      "FANGCHENG_THREE_VIEW":"只锁定方澄身份、后颈低马尾、藏蓝西装与成年比例",
      "STUDIO_DAY_PHOTOREAL":"只锁定日间画室建筑、长桌、左窗、右门和画架",
      "STUDIO_NIGHT_PHOTOREAL":"只锁定夜间画室建筑、木椅、右侧小桌与暖灯冷窗光",
      "PROPERTY_FRONT_DESK_PHOTOREAL_V3":"只锁定空物业前台的柜台、柜后空间和光线",
      "COURT_WINDOW_PHOTOREAL":"只锁定法院窗口、传递槽、读卡区和等候椅"
    }
    for i,asset_id in enumerate(ids,1):
        directives.append(f"@image{i}{labels[asset_id]}。")
    directives.append("人物三视图中的三个身体是同一人的三个角度，成片中每个角色只能出现一人；禁止设定表、分栏、陌生人脸、文字和水印。")
    directives.append("所有视线必须落到剧情指定的真实人物或道具上，头部与眼球同步，禁止看镜头、窗户或画外空处。")
    prefix="参考素材约束："+"".join(directives)+"输出单个竖屏连续电影镜头，严格执行下述已审核剧情："

    style_path=series/"STYLE_REFERENCE_EDITORIAL_COMPRESSION.json"
    style=read(style_path)
    base_prompt=style["shot_prompts"][args.shot_id]
    framework_path=ROOT/"src/content_factory/prompts/seedance_visual_action_v2.md"
    framework=framework_path.read_text(encoding="utf-8").strip()
    acceptance=read(run/"TEXT_ACCEPTANCE.json")
    auth_path=series/"VISUAL_FIRST_AUTHORIZATION.json"
    plan={
      "schema":"creative_seedance_reference_segment_plan/v1",
      "segment_id":args.shot_id,
      "shot_id":args.shot_id,
      "duration_seconds":shot["duration_seconds"],
      "model":"doubao-seedance-2-0-mini-260615",
      "resolution":"720p",
      "ratio":"9:16",
      "seed":926100+number,
      "base_prompt":base_prompt,
      "reference_prompt_prefix":prefix,
      "prompt_framework":{"path":str(framework_path.resolve()),"sha256":sha(framework_path)},
      "prompt":prefix+framework+"\n本镜头已审核剧情："+base_prompt,
      "references":refs,
      "previous_segment":{"receipt":binding(previous/"receipt.json"),"review":binding(previous/"media_review.json")},
      "use_previous_video_reference":needs_video_ref,
      "sources":{
        "screenplay":acceptance["bindings"]["script"],
        "storyboard":acceptance["bindings"]["director"],
        "text_acceptance":binding(run/"TEXT_ACCEPTANCE.json"),
        "assets_accepted":binding(accepted_path),
        "style_revision":binding(style_path),
        "visual_first_authorization":binding(auth_path)
      },
      "performance_run":str(run),
      "video_failure_ledger":str(run.parent/"performance_video_failure_ledger.json"),
      "authorization":"用户要求直接生成完整视频；逐段画面审核通过后继续",
      "style_revision":binding(style_path),
      "visual_first_authorization":binding(auth_path)
    }
    save(args.output_plan,plan)
    print(json.dumps({"shot_id":args.shot_id,"references":ids,"continuous":plan["use_previous_video_reference"],"plan":str(Path(args.output_plan).resolve())},ensure_ascii=False))


if __name__=="__main__":
    main()
