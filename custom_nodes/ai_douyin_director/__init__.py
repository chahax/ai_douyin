"""Dependency-free ComfyUI directing workbench; never submits paid jobs."""
import hashlib
import json

WEB_DIRECTORY = "./js"

FIELDS = {
    "story_lock": "原稿锁定：人物身份、唯一对白、核心动作、道具归属，不在此改剧情",
    "intent": "本镜让观众发现什么；人物想得到什么，阻碍是什么",
    "start_state": "首态：位置、视线、左右手与道具状态；续段以已审原始尾帧为准",
    "composition": "景别、机位、轴线、主体落点；前景/中景/背景分别服务于什么",
    "lighting": "光源方向、明暗层次、色温与材质；同场景保持一致",
    "camera": "一个主要运镜及其起止时刻、叙事动机；无动机则固定",
    "performance": "情绪起点→触发→终点；落实到视线、呼吸、面部和动作力度",
    "beats": "按秒写可见动作；对白可并行；不靠空等或反复手势填时长",
    "audio": "说话人、声线、对白起点、重音、语速及环境声；不要配错角色",
    "end_state": "尾态：人物、视线、左右手、道具落点；下一段如何接续",
    "constraints": "本镜具体禁项；不要字幕水印、身份漂移、道具瞬移或重复动作",
}


def compile_card(card):
    if not isinstance(card, dict) or card.get("schema") != "director_card/v1":
        raise ValueError("需要 director_card/v1 对象")
    if card.get("continuity") not in ("opening", "raw_tail_continuation"):
        raise ValueError("continuity 必须为 opening 或 raw_tail_continuation")
    duration = card.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, int) or not 4 <= duration <= 15:
        raise ValueError("duration_seconds 必须为4—15整数秒")
    for key in ("shot_id", *FIELDS):
        if not isinstance(card.get(key), str) or not card[key].strip():
            raise ValueError(f"缺少非空文本字段：{key}")
    prefix = f"竖屏剧情镜头 {card['shot_id']}，{duration}秒。"
    if card["continuity"] == "raw_tail_continuation":
        prefix += "从上一段已审核通过的原始尾帧连续开始，不复位人物、道具或机位，不重演上一动作。"
    prompt = prefix + "\n" + "\n".join(
        f"【{FIELDS[key].split('：')[0] if key == 'story_lock' else key}】{card[key]}"
        for key in FIELDS
    )
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    packet = {
        "schema": "director_candidate/v1", "card": card,
        "prompt": prompt, "prompt_sha256": digest,
        "text_review": "pending", "media_review": "pending",
        "production_authorized": False,
        "checks": ["锁稿对白和动作逐字核对", "逐秒表演和运镜可执行性", "首尾与镜内动作抽帧",
                   "同步听看说话人、声线、口型和语速", "相邻切点人物、视线、手和道具连续性"],
    }
    return prompt, json.dumps(packet, ensure_ascii=False, indent=2)


class DouyinDirectorCard:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "shot_id": ("STRING", {"default": "S01"}),
            "duration_seconds": ("INT", {"default": 6, "min": 4, "max": 15}),
            "continuity": (["opening", "raw_tail_continuation"],),
            **{key: ("STRING", {"default": "", "multiline": True, "tooltip": hint})
               for key, hint in FIELDS.items()},
        }}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("seedance_prompt_candidate", "review_packet_json")
    FUNCTION = "build"
    CATEGORY = "AI Douyin/导演台"

    def build(self, **kwargs):
        return compile_card({"schema": "director_card/v1", **kwargs})


class DouyinDirectorPreview:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"prompt": ("STRING", {"forceInput": True}),
                             "review_packet": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "preview"
    CATEGORY = "AI Douyin/导演台"

    def preview(self, prompt, review_packet):
        return {"ui": {"text": [prompt, review_packet]}}


NODE_CLASS_MAPPINGS = {"DouyinDirectorCard": DouyinDirectorCard,
                       "DouyinDirectorPreview": DouyinDirectorPreview}
NODE_DISPLAY_NAME_MAPPINGS = {"DouyinDirectorCard": "导演台 · 镜头卡",
                              "DouyinDirectorPreview": "导演台 · 待审提示词"}
