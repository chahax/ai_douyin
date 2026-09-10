"""Offline, source-bound Qwen analysis of all sampled frames and local ASR text."""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.trend_intelligence.content_analysis.artifacts import (
    parse_model_json, read_json, sha256, transcript_evidence, validate_expression, verify_expression_evidence, write_json,
)
from src.trend_intelligence.content_analysis.hierarchical import VisualBatchCheckpoint, synthesize_expression

DEFAULT_MODEL = PROJECT_ROOT / ".local_models" / "video_analysis" / "Qwen3-VL-4B-Instruct"
PROMPT_VERSION = "source-expression-v5-expression-function-and-attribution"
DEFAULT_PROMPT = """你查看的是同一条视频按时间排序的真实抽帧。每图前给出frame_id及解码时间。
仅据图像描述可观察事实，不根据人物外貌猜真实身份，不把字幕当成实际声音。
先区分主画面、画中画/插入特写、字幕层。插入小窗的手或道具不能归属于背景出镜人物；看不出操作者就写“小窗中一只手”。普通讲解者手势不等于在操作小窗里的物件。没有纸张的帧不能说“站在文件前”。
单帧只能证明姿势和物件状态；动作变化须有前后帧可见差异，不因字幕写“转动”就断言单帧手正在旋转。只抄清晰文字；不要根据场景补写纸上条款，不用“暗示”添加法律含义。各帧简洁记录最有区分度的事实，避免反复复述衣服和背景。
返回严格JSON：{"observations":[{"frame_id":"V0001","event":"具体可见人物动作、实物/纸张/屏幕、相互位置、表情、构图、可辨认文字及与前图的变化；无变化如实写"}],"uncertainties":["抽帧之间不可见动作等"]}。
必须覆盖本次全部frame_id，不得新增ID。特别留意实物示范的步骤和状态变化、人物阻拦/争抢/拒绝/提出要求等可见行为。
每批沿用输入中的真实frame_id，禁止从V0001重新编号。笔记本背盖遮挡键盘时不能确认键盘操作；屏幕上的静态标题不等于软件操作。手语窗口、新闻包装和主讲画面分别描述，眼睛/手部被遮挡则写不可见，不把某一帧闭眼或抬指延续到其他帧。
不能只因出现两人就认定冲突；不能把口播提问当成情节冲突。音色、说话人匹配、语气、音乐、音效不能由静帧确认。"""
SYNTHESIS_PROMPT = """基于给出的带时间戳画面观察与本地ASR转写，分析该原视频核心表达及表达方式，用于研究原创创作形式。
core_message.text必须填写本视频实际传达的具体内容、疑虑或论点。即使只有一个提问、没有给答案，也归纳提出的具体问题，不要求视频有最终知识结论。不要原样复制字段说明。
核心用约80–200个汉字概括一条主线，省略无关匿名姓名和逐秒流水账，引用2–8条直接支持核心的证据；完整细节已在原始证据中保留，不必把全片所有ID列入核心。每条视觉/语言手法只写一个明确要点并给必要引用，避免整段抄录所有字幕。
归纳核心表达时保留ASR中的关键前提、条件和因果对象，不把人物的担忧写成已经发生的事实，不把具体的证据/程序问题改写成宽泛法律结论；不确定时贴近证据原句。
保留原文动作的主语、宾语和目的；操作建议不能改成鉴别现象。例如“把多页纸错开再盖骑缝章”不等于“识别页码错位”；“写上以下空白”不等于“填写条款”。多个并列风险不能拼接成新的因果关系。所有关键结论先核对对应ASR原句和画面事实，不能只追求短句或戏剧性。
区分主画面讲解、插入特写的实物操作和字幕说明；无法确认是同一操作者时不能合并角色。仅有ASR和静帧不能断言是旁白还是同步出镜讲话，可写“转写文本采用…结构”。
ASR只是识别文字，可能错词；不证明真实声音、声线、情绪、语速、口型。仅能分析对白文本的结构/措辞/问答/旁白措辞，听觉表现一律未知。
所有结论必须引用给出的evidence id。事实与推测分开；不可引用标题、热度或外部知识替代媒体证据。
归纳原作者表达时注明这是“视频建议/视频主张”，不要把原片经验建议升级为已核实的法律结论或效果保证。视觉手法的每个操作需引用真正显示该物态的帧，不能只引开场帧支撑后段写字、按印等步骤。若仅看到跨页指印，不能说已看到实体印章盖下；字幕/ASR说盖章与实际可见印记分开描述。
实物教学必须描述物件承担的展示/验证作用及可见步骤；冲突必须区分角色目标、相互阻碍、损失代价、动作造成的转折和结果。只有问题+知识回答时不得说成冲突。没有冲突可status=not_observed；证据不足用unknown。不要为了生成戏剧而强行宣称原片有冲突。
模式判定依据表达功能，不依据有没有问号：催款、拒绝、逼对方履约等明确目标受到阻碍，即使台词全是反问、对方仅有反应镜头，也属于可观察的人物冲突；不能概括成中性知识问答。真正知识问答才用question_answer。冲突角色目标只写证据支持的诉求，不为沉默人物虚构“厘清责任”等目标。ASR未区分说话人时须保留归属未知。
不得把夸张反问当作剧情事实或新的法律主题，例如“甲方死了你死不死”是质疑拒付理由，不能归纳为死亡引发连带责任。核心表达优先写具体行动诉求及阻碍，不泛化成抽象责任问题。原片未展示付款或和解时须明确结局未出现，不能说问题已解决。
区分原片叙述的结果与是否出示真实证明：ASR明确讲述法院驳回/签字/离开等结果时，应保留“讲述者称…”的叙事结果；没有判决文书、收款或执行实拍，只能说结果未经核验，不能因此概括成“未交代结局”。
仅输出严格JSON对象，字段：
{"schema":"video_expression_analysis/v1","core_message":{"text":"观众最后理解/感受到什么","evidence_ids":["V0001","A0001"]},"expression_modes":[{"mode":"prop_demonstration/conflict_drama/direct_explanation/question_answer/case_reenactment/screen_demonstration/text_cards/interview/mixed/unknown之一","evidence_ids":["V0001"]}],"visual_expression":[{"text":"具体视觉表达手法/动作/道具作用/开场钩子/如何交代结局","evidence_ids":["V0001"]}],"audio_expression":[{"text":"只根据ASR文本的语言结构，不称已听到语气或音效","evidence_ids":["A0001"]}],"conflict":{"status":"observed/not_observed/unknown之一","characters":[{"role":"非真实姓名的角色","goal":"有证据的行动目标","evidence_ids":["A0001"]}],"trigger":{"text":"有证据才填写否则空串","evidence_ids":[]},"opposition":{"text":"有证据才填写否则空串","evidence_ids":[]},"stakes":{"text":"有证据才填写否则空串","evidence_ids":[]},"turning_point":{"text":"有证据才填写否则空串","evidence_ids":[]},"resolution":{"text":"可见结局或文本结论，没有则空串","evidence_ids":[]}},"uncertainties":["音色、语气、音效、口型未分析；抽帧不能证明连续动作"]}。
mode/status必须只输出一个枚举值，不要输出整个选项串；未知信息填空而非无依据填写。
expression_modes可以有多项，每项一个枚举值。能确认实物示范、现场人物冲突、真人讲解、文字卡片等具体手法时分别列出并引用证据，不要用单独mixed掩盖可分解的手法；mixed只用于证据不足以进一步区分的组合形式。素材插图或模糊B-roll不等于案例复现，只有明确以角色和行动重演事件才用case_reenactment。
screen_demonstration需要可见的软件界面、屏幕内操作或界面步骤演示；插入人群、事故车辆、书本等配图不属于屏幕操作演示。text_cards需要文字卡片本身承担信息展示，不能仅因有普通随讲解字幕就添加该模式。来源把一句话称为法规或条文，仍只能写“讲述者声称的依据/画面展示的来源主张”，不得声称已经核实法条原文。字幕中的“张某 某公司员工”等相邻信息先按角色/单位断句，不能误拼成姓名。
先判表达功能再选模式：手边放纸、抬指、使用笔记本背面作背景均不是实物教学；桌后静态主题屏、电视新闻包装不是软件演示；口播普通字幕及结束时残留的黑底字幕不是独立文字卡片。单人转述案件、静态法庭配图不是角色重演。若文字扮演多方对立对白而画面仅一个人，必须明确“文本模拟对话”，不能扩成多人现场表演。
每项实物步骤先标明它是错误示范、正确操作还是尚未发生的风险；把错误动作当建议会使整个分析失真。说话人称谓不等于发言主体；不同协会/公司/合同的事实分开，签约金额不等于损失或涉诈金额，口述请求不等于已判结果。日期未给年份或法条依据时保留未知。
每项引用覆盖该句所有必要前提和后果，ASR跨段断句须连读相邻原文，不能遗漏“可能、没有、双方、生效、违约”等条件。引用只留直接支持该主张的证据，避免泛引整片；长叙事主线确需更多引用时允许超过2–8条建议，不能为压缩引用删掉后半段或混淆对象。“全程、始终、同步”等绝对表述没有相应连续证据时改为明确抽查范围。
conflict的trigger/opposition/stakes/turning_point/resolution必须各是{"text":"","evidence_ids":[]}对象，不能直接变成字符串。
注意JSON中的中文字段说明都要替换为对本视频的实际分析；core_message不能为空，不能是‘观众最后理解/感受到什么’等说明文字。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--frame-manifest", type=Path, required=True)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--max-images", type=int, default=6, help="Images per inference batch, not a whole-video cap")
    parser.add_argument("--max-new-tokens", type=int, default=4000)
    parser.add_argument("--low-memory", action="store_true", help="NF4 model, two-frame maximum, limited CPU threads")
    parser.add_argument("--visual-responses-from", type=Path,
                        help="Reuse strictly verified raw visual responses without rerunning completed observations")
    parser.add_argument("--visual-responses-batch-size", type=int, default=6)
    parser.add_argument("--visual-responses-plan", type=Path,
                        help="JSON list of original response directories, batch sizes and exact inference configurations")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--synthesis-provider", choices=("local_qwen", "configured_llm"), default="local_qwen")
    parser.add_argument("--synthesis-feedback-file", type=Path)
    parser.add_argument("--observation-review", type=Path,
                        help="Explicit source-bound visual corrections from actual frame inspection")
    parser.add_argument("--synthesis-from", type=Path,
                        help="Reuse verified Qwen observations for text-only synthesis, with at most one schema repair")
    return parser.parse_args()


def sample_frames(frame_dir: Path, limit: int) -> list[Path]:
    if limit < 1:
        raise ValueError("max-images must be positive")
    frames = sorted(p for p in frame_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not frames:
        raise RuntimeError(f"No frames found in {frame_dir}")
    return frames


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.max_images < 1:
        raise ValueError("max-images must be positive")
    if args.low_memory:
        args.max_images = min(args.max_images, 2)
        for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            os.environ[key] = "2"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        os.environ["HF_ENABLE_PARALLEL_LOADING"] = "false"
    if sum(bool(value) for value in (args.synthesis_from, args.visual_responses_from, args.visual_responses_plan)) > 1:
        raise ValueError("choose one complete analysis, raw directory or raw response plan for reuse")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    manifest_path = args.frame_manifest.resolve()
    manifest = read_json(manifest_path)
    if manifest.get("schema") != "local_video_frame_manifest/v2":
        raise ValueError("a source-bound v2 decoded frame manifest is required")
    if sha256(manifest["source_video_path"]) != manifest["source_video_sha256"]:
        raise ValueError("source video changed after frame extraction")
    frames = manifest.get("frames") or []
    if not frames:
        raise ValueError("frame manifest is empty")
    for frame in frames:
        if sha256(frame["path"]) != frame["sha256"]:
            raise ValueError("sampled frame changed")
    # Running children retain their loaded code. This source-bound policy takes
    # effect only when the serial queue starts a subsequent analyzer process.
    from src.trend_intelligence.content_analysis.resource_policy import (
        probe_resources, resolve_resource_policy, resource_inference_configuration,
    )
    checkpoint_root = PROJECT_ROOT / "data/video_analysis/checkpoints" / manifest["source_video_sha256"]
    resource_selection = (resolve_resource_policy(
        PROJECT_ROOT / "data/video_analysis/resource_policy.json", manifest["source_video_sha256"],
        checkpoint_root / "resource_selection.json",
    ) if not args.synthesis_from else None)
    if resource_selection:
        args.low_memory = resource_selection["low_memory"]
        args.max_images = resource_selection["max_images"]
        write_json(args.output.with_name("resource_selection.json"), resource_selection)
        print(f"Resource policy selected {resource_selection['resource_mode']}: "
              f"{resource_selection['quantization']}, batch {args.max_images}; "
              f"{resource_selection['selection_reason']}", flush=True)
    transcript = read_json(args.transcript) if args.transcript else {}
    asr_evidence = transcript_evidence(transcript)
    previous = read_json(args.synthesis_from) if args.synthesis_from else None
    if previous is not None:
        if (previous.get("schema") != "local_qwen_frame_analysis/v2" or
                previous.get("source_video_sha256") != manifest["source_video_sha256"] or
                previous.get("frame_manifest_sha256") != sha256(manifest_path) or
                previous.get("transcript_sha256") != (sha256(args.transcript) if args.transcript else None)):
            raise ValueError("reused visual analysis input hashes differ from this synthesis input")
        verify_expression_evidence(previous["answer"]["expression_analysis"], manifest, transcript,
                                   visual_batches=previous.get("batches") or [],
                                   observation_review=previous.get("observation_review"))
    prompt = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else DEFAULT_PROMPT
    model_path = args.model.resolve()
    processor, model, torch = None, None, None
    image_pixels = {"shortest_edge": 65536, "longest_edge": 262144}
    inference_configuration = {"quantization": "nf4_double" if args.low_memory else "none",
                               "image_pixels": image_pixels, "max_new_tokens": args.max_new_tokens}
    if resource_selection:
        inference_configuration = resource_inference_configuration(
            resource_selection, image_pixels=image_pixels, max_new_tokens=args.max_new_tokens)

    def unload_local_model():
        nonlocal processor, model
        processor, model = None, None
        gc.collect()
        if torch is not None:
            torch.cuda.empty_cache()

    def wait_for_memory(minimum_gib: float):
        if resource_selection:
            minimum_gib = resource_selection["minimum_load_ram_gib"]
            minimum_vram = resource_selection["minimum_load_vram_gib"]
            while True:
                resources = probe_resources()
                if (resources["available_ram_gib"] >= minimum_gib
                        and resources["available_vram_gib"] is not None
                        and resources["available_vram_gib"] >= minimum_vram):
                    return
                print(f"Waiting for resources: need {minimum_gib:g} GiB RAM and {minimum_vram:g} GiB VRAM; "
                      "completed observations are saved", flush=True)
                time.sleep(15)
        if not args.low_memory:
            return
        import psutil
        while psutil.virtual_memory().available < minimum_gib * 2**30:
            print(f"Waiting for memory: need {minimum_gib:g} GiB available; completed observations are saved", flush=True)
            time.sleep(15)

    def load_local_model():
        nonlocal processor, model, torch
        if model is not None:
            return
        wait_for_memory(6)
        import torch as torch_runtime
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration, BitsAndBytesConfig
        torch = torch_runtime
        if args.low_memory:
            torch.set_num_threads(2)
        if not torch.cuda.is_available():
            raise RuntimeError("local Qwen requires CUDA; no metadata fallback")
        print(f"Loading local Qwen for {len(frames)} frames in batches of {args.max_images}...", flush=True)
        processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
        if hasattr(processor, "image_processor"):
            processor.image_processor.size = image_pixels
        loading_options = {}
        if args.low_memory:
            loading_options["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            model_path, dtype=torch.bfloat16, device_map="cuda:0", local_files_only=True,
            low_cpu_mem_usage=True, attn_implementation="sdpa", **loading_options,
        ).eval()
        print(f"Local model loaded: {inference_configuration['quantization']}; "
              f"weights {model.get_memory_footprint() / 2**30:.2f} GiB", flush=True)

    inference_index = max((int(path.stem.rsplit("_", 1)[-1])
                           for path in args.output.parent.glob("qwen_response_*.json")
                           if path.stem.rsplit("_", 1)[-1].isdigit()), default=0)
    def infer(content: list[dict]) -> dict:
        nonlocal inference_index
        inference_index += 1
        if (args.low_memory or resource_selection) and model is not None:
            import psutil
            release_below = resource_selection["release_below_ram_gib"] if resource_selection else 2
            if psutil.virtual_memory().available < release_below * 2**30:
                print("Memory pressure: releasing local model before continuing", flush=True)
                unload_local_model()
        load_local_model()
        started_at = datetime.now(timezone.utc).isoformat()
        start_clock = time.perf_counter()
        inputs = processor.apply_chat_template(
            [{"role": "user", "content": content}], tokenize=True, add_generation_prompt=True,
            return_dict=True, return_tensors="pt",
        ).to(model.device)
        if inputs.input_ids.shape[-1] > 24576:
            raise ValueError("local Qwen input exceeds 24576 tokens; split the evidence upstream")
        with torch.inference_mode():
            output_ids = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False, use_cache=True)
        answer = processor.batch_decode([out[len(inp):] for inp, out in zip(inputs.input_ids, output_ids)],
                                        skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
        # Preserve the actual model output even when JSON/schema validation fails.
        write_json(args.output.with_name(f"qwen_response_{inference_index:03d}.json"),
                   {"answer": answer, "input": content, "model": str(model_path),
                    "inference_configuration": inference_configuration,
                    "resource_selection": resource_selection,
                    "started_at": started_at, "elapsed_seconds": round(time.perf_counter()-start_clock, 3),
                    "input_tokens": int(inputs.input_ids.shape[-1]),
                    "output_tokens": int(output_ids.shape[-1]-inputs.input_ids.shape[-1]),
                    "created_at": datetime.now(timezone.utc).isoformat()})
        del inputs, output_ids
        if args.low_memory or resource_selection:
            gc.collect()
            torch.cuda.empty_cache()
        return parse_model_json(answer)

    batches, evidence = [], []
    binding = {"source_sha256": manifest["source_video_sha256"], "model": str(model_path),
               "prompt_version": PROMPT_VERSION, "visual_prompt": prompt,
               "max_images": args.max_images, "max_new_tokens": args.max_new_tokens,
               "image_pixels": image_pixels,
               "hierarchical_sha256": sha256(PROJECT_ROOT / "src/trend_intelligence/content_analysis/hierarchical.py")}
    if args.low_memory or resource_selection:
        binding["inference_configuration"] = inference_configuration
    visual_cache = VisualBatchCheckpoint(checkpoint_root / "visual_batches", binding=binding)
    imported_rows, visual_imports = {}, []
    if args.visual_responses_from or args.visual_responses_plan:
        from src.trend_intelligence.content_analysis.visual_response_import import read_visual_response_plan
        plans = (json.loads(args.visual_responses_plan.read_text(encoding="utf-8")) if args.visual_responses_plan else
                 [{"directory": str(args.visual_responses_from), "batch_size": args.visual_responses_batch_size}])
        imports = read_visual_response_plan(plans, manifest, model_path=model_path, prompt=prompt)
        for captured in imports:
            visual_imports.append(captured["provenance"])
            for row in captured["result"]["observations"]:
                if row["frame_id"] in imported_rows:
                    raise ValueError("visual response plan includes overlapping frame observations; choose one origin per frame")
                imported_rows[row["frame_id"]] = row
        print(f"Reusing {len(imported_rows)} captured observations with their original configuration", flush=True)
    visual_inference_count = 0
    if previous is not None:
        batches = previous["batches"]
        evidence = [item for item in previous["answer"]["expression_analysis"]["evidence"] if item["channel"] == "visual"]
        print("Reusing hash-verified frame observations; image inference and ASR skipped", flush=True)
    for offset in (range(0, len(frames), args.max_images) if previous is None else []):
        chunk = frames[offset:offset + args.max_images]
        content: list[dict] = []
        for frame in chunk:
            content.extend([{"type": "text", "text": f"{frame['id']}，{frame['time_seconds']:.3f}秒"},
                            {"type": "image", "image": frame["path"]}])
        content.append({"type": "text", "text": prompt})
        result = visual_cache.load(chunk)
        # Imported observations retain their old inference provenance; never write
        # these regrouped rows into a cache labelled with the new NF4 configuration.
        if result is None and all(frame["id"] in imported_rows for frame in chunk):
            result = {"observations": [imported_rows[frame["id"]] for frame in chunk],
                      "uncertainties": list(dict.fromkeys(note for captured in imports
                          if any(row["frame_id"] in {f["id"] for f in chunk}
                                 for row in captured["result"]["observations"])
                          for note in captured["result"].get("uncertainties", [])))}
        if result is None:
            result = infer(content)
            visual_inference_count += 1
            visual_cache.save(chunk, result)
        observed = {str(item.get("frame_id")): str(item.get("event") or "").strip()
                    for item in result.get("observations") or [] if isinstance(item, dict)}
        if set(observed) != {item["id"] for item in chunk} or not all(observed.values()):
            raise ValueError("Qwen response did not observe every sampled frame")
        for frame in chunk:
            evidence.append({"id": frame["id"], "channel": "visual", "start_seconds": frame["time_seconds"],
                             "end_seconds": frame["time_seconds"], "text": observed[frame["id"]]})
        batches.append(result)
        print(f"Observed {min(offset + args.max_images, len(frames))}/{len(frames)} frames", flush=True)
    observation_review = args.observation_review or (previous.get("observation_review") if previous else None)
    if observation_review:
        from src.trend_intelligence.content_analysis.reviewed_observations import apply_reviewed_observations
        reviewed = apply_reviewed_observations(manifest, batches, observation_review)
        evidence = reviewed["evidence"]
        observation_review = reviewed["review"]
    evidence.extend(asr_evidence)
    synthesis_prompt = SYNTHESIS_PROMPT
    feedback_text = args.synthesis_feedback_file.read_text(encoding="utf-8") if args.synthesis_feedback_file else ""
    synthesis_infer, synthesis_identity = infer, {"provider": "local_qwen", "model": str(model_path)}
    if args.synthesis_provider == "configured_llm":
        unload_local_model()
        from src.trend_intelligence.content_analysis.text_synthesis import ConfiguredTextSynthesis
        synthesis_infer = ConfiguredTextSynthesis(args.output.parent)
        synthesis_identity = synthesis_infer.identity
    print(f"Synthesizing source expression using {args.synthesis_provider}; media files remain local", flush=True)
    expression, synthesis_provenance = synthesize_expression(
        evidence, float(manifest["duration_seconds"]), infer=synthesis_infer, synthesis_prompt=synthesis_prompt,
        checkpoint_dir=(args.output.parent / "synthesis_stages" if previous is not None
                        else checkpoint_root / "synthesis_stages"),
        binding={**binding, "synthesis_identity": synthesis_identity,
                 "observation_review": observation_review,
                 "transcript_sha256": sha256(args.transcript) if args.transcript else None},
        max_input_chars=64000 if args.synthesis_provider == "configured_llm" else 11000,
        max_claim_refs=32 if args.synthesis_provider == "configured_llm" else 3,
        max_claim_chars=360 if args.synthesis_provider == "configured_llm" else 120,
        max_claims=12 if args.synthesis_provider == "configured_llm" else 6,
        allow_final_repair=True, feedback_text=feedback_text,
    )
    verify_expression_evidence(expression, manifest, transcript, visual_batches=batches,
                               observation_review=observation_review)
    expression["uncertainties"] = list(dict.fromkeys([*(expression.get("uncertainties") or []),
        "核心表达及表达方式属于模型自动归纳候选，未获人工语义通过；文件和结构校验不能证明归纳事实准确。"]))
    payload = {
        "schema": "local_qwen_frame_analysis/v2", "created_at": datetime.now(timezone.utc).isoformat(),
        "semantic_status": "model_candidate_unreviewed",
        "model": str(model_path), "prompt_version": PROMPT_VERSION,
        "inference_configuration": inference_configuration,
        "resource_selection": resource_selection,
        "synthesis_provenance": synthesis_provenance,
        "synthesis_identity": synthesis_identity,
        "synthesis_feedback": ({"path": str(args.synthesis_feedback_file.resolve()),
                                "sha256": sha256(args.synthesis_feedback_file)}
                               if args.synthesis_feedback_file else None),
        "observation_review": observation_review,
        "source_video_sha256": manifest["source_video_sha256"], "frame_manifest_path": str(manifest_path),
        "frame_manifest_sha256": sha256(manifest_path),
        "transcript_sha256": sha256(args.transcript) if args.transcript else None,
        "frames": [item["path"] for item in frames], "analyzed_frame_ids": [item["id"] for item in frames],
        "prompt": prompt, "synthesis_prompt": SYNTHESIS_PROMPT, "batches": batches,
        "visual_inference_performed": visual_inference_count > 0,
        "visual_inference_batch_count": visual_inference_count,
        "visual_response_imports": visual_imports,
        "reused_visual_analysis": ({"path": str(args.synthesis_from.resolve()), "sha256": sha256(args.synthesis_from),
                                    "original_visual_prompt": previous.get("prompt")} if previous else None),
        "answer": {"summary": expression["core_message"]["text"], "expression_analysis": expression,
                   "visual_timeline": [{"time": f"{item['start_seconds']}秒", "event": item["text"]}
                                       for item in evidence if item["channel"] == "visual"],
                   "uncertainties": expression.get("uncertainties") or []},
    }
    write_json(args.output.resolve(), payload)
    print(f"Wrote source-bound Qwen analysis: {args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
