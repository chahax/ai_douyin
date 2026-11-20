from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1" / "v2_debate"
MODEL_DIR = ROOT / "data" / "models" / "kokoro" / "Kokoro-82M-v1.1-zh"
REPO_ID = "hexgrad/Kokoro-82M-v1.1-zh"
SAMPLE_RATE = 24_000


LINES = [
    ("02", "周宁", "zf_048", 1.16, "同一组转账，前案认为部分款项不能按照借款支持，后案为什么仍然判令返还？"),
    ("04", "顾承", "zm_052", 1.14, "因为后案换了问题。它不再只问是不是借款，而是审查收款方有没有按照双方约定的投资用途履行。"),
    ("05", "顾承", "zm_052", 1.16, "请求权基础一变，证据的组织方式也会变。原告不能把全部转账，都塞进同一个借款故事。"),
    ("07", "许安", "zf_001", 1.18, "但汇款摘要写着投资，也可能只是付款方单方备注。口头指示、合作习惯和项目支出，都可能改变它的含义。"),
    ("08", "周宁", "zf_048", 1.17, "所以第一轮交锋，不是争谁的声音更大，而是还原双方究竟约定了什么。"),
    ("10", "顾承", "zm_052", 1.14, "本案的关键，是收款方先后解释成书画款、药品费和科技项目。解释彼此冲突，可信度就会下降。"),
    ("11", "许安", "zf_001", 1.18, "不过，解释不一致也不当然等于虚假。还要看合同、发票、付款对象和项目进度，能不能组成另一条完整证据链。"),
    ("13", "周宁", "zf_048", 1.15, "这时举证责任开始移动。付款方先证明转账和约定用途；控制资金流向的一方，要说明钱最终去了哪里。"),
    ("14", "顾承", "zm_052", 1.16, "如果实际流向与约定用途对不上，又没有第三方凭证印证，返还请求就获得了支撑。"),
    ("16", "许安", "zf_001", 1.18, "如果合同、发票、收款对象和项目成果能够逐项对应，收款方的抗辩也可能成立。法庭看的是印证，不是标签。"),
    ("17", "顾承", "zm_052", 1.15, "还要逐笔拆分不同批次的金额、时间和备注。不能用一条结论，覆盖全部交易。"),
    ("19", "许安", "zf_001", 1.17, "前案的判断当然重要，但不能机械替代后案审查。诉讼请求、待证事实和证据结构不同，结论就可能不同。"),
    ("20", "周宁", "zf_048", 1.15, "从付款方角度，要补强约定用途和资金偏离；从收款方角度，要还原履行过程和第三方凭证。"),
    ("22", "顾承", "zm_052", 1.16, "诉讼不是只找对自己有利的一句话，而是提前验证，对方最强的解释能不能被证据击破。"),
    ("23", "周宁", "zf_048", 1.13, "这就是裁判文书研究的价值。同一事实，在不同请求权和证据结构下，可能通向不同结果。专业，是让当事人在行动前看清每一条路径。"),
]


def probe(path: Path) -> float:
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path)
    ], text=True).strip())


def main() -> int:
    import numpy as np
    import soundfile as sf
    from kokoro import KModel, KPipeline

    audio_dir = OUT / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(ROOT / "data" / "cache" / "huggingface"))
    model = KModel(
        repo_id=REPO_ID,
        config=str(MODEL_DIR / "config.json"),
        model=str(MODEL_DIR / "kokoro-v1_1-zh.pth"),
    ).to("cpu").eval()
    pipeline = KPipeline(lang_code="z", repo_id=REPO_ID, model=model, device="cpu")
    timeline = []
    for shot_id, speaker, voice, speed, text in LINES:
        chunks = []
        for result in pipeline(text, voice=str(MODEL_DIR / "voices" / f"{voice}.pt"), speed=speed):
            if result.audio is not None:
                chunks.append(result.audio.detach().cpu().numpy().astype(np.float32))
        if not chunks:
            raise RuntimeError(f"No audio for {shot_id}")
        wav = audio_dir / f"{shot_id}_{voice}.wav"
        sf.write(wav, np.concatenate(chunks), SAMPLE_RATE, subtype="PCM_16")
        duration = probe(wav)
        timeline.append({
            "id": shot_id, "speaker": speaker, "voice": voice, "speed": speed,
            "text": text, "file": str(wav), "duration": round(duration, 3)
        })
        print(f"{shot_id} {speaker} {duration:.3f}s", flush=True)
    (audio_dir / "timeline.json").write_text(json.dumps({"timeline": timeline}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
