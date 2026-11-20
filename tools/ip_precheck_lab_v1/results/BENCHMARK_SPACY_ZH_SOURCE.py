"""Offline entity-extraction trial; candidates are references, never copyright verdicts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import socket
import sys
import warnings


ROOT = Path(__file__).resolve().parent
LABELS = ["person", "brand", "organization", "location", "work of art",
          "fictional character", "creator"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def deny_network() -> None:
    """Defence in depth alongside offline HF settings; not an OS sandbox."""
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                       "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"})

    def denied(*args, **kwargs):
        raise RuntimeError("Network access is disabled during this local trial")

    socket.create_connection = denied
    socket.getaddrinfo = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.socket.sendto = denied


def chunk_text(text: str, size: int, overlap: int):
    """Overlapping character windows cover every character, including whitespace."""
    if size < 32 or not 0 <= overlap < size:
        raise ValueError("Require chunk_chars >= 32 and 0 <= overlap < chunk_chars")
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        yield start, end, text[start:end]
        if end == len(text):
            break
        start = end - overlap


def infer_ner(model, text: str, labels: list[str], threshold: float,
              chunk_chars: int, overlap: int, progress: str = ""):
    chunks, merged = [], {}
    for index, (start, end, content) in enumerate(chunk_text(text, chunk_chars, overlap)):
        raw = model.predict_entities(content, labels, threshold=threshold)
        mapped = []
        for item in raw:
            left, right = int(item["start"]), int(item["end"])
            if not 0 <= left < right <= len(content):
                raise ValueError(f"Invalid model offsets: {item!r}")
            if content[left:right] != item["text"]:
                raise ValueError(f"Model offsets do not match raw text: {item!r}")
            entity = {"start": start + left, "end": start + right,
                      "text": item["text"], "label": item["label"],
                      "score": float(item["score"])}
            mapped.append(entity)
            key = (entity["start"], entity["end"], entity["label"])
            if key not in merged or entity["score"] > merged[key]["score"]:
                merged[key] = entity
        chunks.append({"index": index, "start": start, "end": end,
                       "text": content, "raw_entities": raw,
                       "global_entities": mapped})
        if progress:
            print(f"{progress}: chunk {index + 1}, chars {start}:{end}",
                  file=sys.stderr, flush=True)
    return {"entities": sorted(merged.values(),
                              key=lambda x: (x["start"], x["end"], x["label"])),
            "chunks": chunks, "coverage_characters": len(text),
            "deduplication": "same global start/end/label; highest score kept"}


class DictionaryMatcher:
    def __init__(self, dictionary):
        import spacy

        self.entries = {entry["id"]: entry for entry in dictionary["entries"]}
        self.nlp = spacy.blank("zh")
        ruler = self.nlp.add_pipe("entity_ruler", config={
            "phrase_matcher_attr": "LOWER", "validate": True})
        ruler.add_patterns([
            {"label": entry["label"], "pattern": alias, "id": entry["id"]}
            for entry in dictionary["entries"] for alias in entry["aliases"]
        ])

    @staticmethod
    def clause(text: str, start: int, end: int) -> str:
        # Restrict ambiguous alias heuristics to the same punctuation clause.
        delimiters = list(re.finditer(r"[，,。；;！？!?\n]", text))
        left = max((m.end() for m in delimiters if m.end() <= start), default=0)
        right = min((m.start() for m in delimiters if m.start() >= end),
                    default=len(text))
        return text[left:right]

    def match(self, text: str):
        accepted, rejected = [], []
        for span in self.nlp(text).ents:
            entry = self.entries[span.ent_id_]
            alias_rules = {key.casefold(): value for key, value in
                           entry.get("conditional_aliases", {}).items()}
            required = alias_rules.get(span.text.casefold(), [])
            context = self.clause(text, span.start_char, span.end_char)
            item = {"start": span.start_char, "end": span.end_char,
                    "text": span.text, "label": span.label_, "score": None,
                    "canonical_id": entry["id"], "canonical": entry["canonical"],
                    "candidate_kind": entry["candidate_kind"],
                    "source_kind": entry["source_kind"],
                    "source_note": entry["source_note"],
                    "matched_context": context, "required_context_any": required}
            if required and not any(word.casefold() in context.casefold()
                                    for word in required):
                item["reason"] = "ambiguous alias lacks configured local context"
                rejected.append(item)
            else:
                item["reason"] = "demo EntityRuler alias and context rule matched"
                accepted.append(item)
        return {"candidates": accepted, "rejected_ambiguous_matches": rejected,
                "score_policy": "rule matches have no probability score"}


def metric(predicted: list[dict], expected: list[dict], *, labels: bool = True):
    def key(item):
        fields = (item["start"], item["end"])
        return fields + (item["label"],) if labels else fields

    p, e = {key(x): x for x in predicted}, {key(x): x for x in expected}
    tp, fp, fn = set(p) & set(e), set(p) - set(e), set(e) - set(p)
    return {"tp": len(tp), "fp": len(fp), "fn": len(fn),
            "precision": len(tp) / len(p) if p else None,
            "recall": len(tp) / len(e) if e else None,
            "false_positives": [p[k] for k in sorted(fp)],
            "false_negatives": [e[k] for k in sorted(fn)]}


def validate_gold(cases) -> None:
    seen = set()
    for case in cases:
        if case["id"] in seen:
            raise ValueError("Duplicate case ID")
        seen.add(case["id"])
        for field in ("expected_ner", "expected_candidates"):
            for item in case[field]:
                start, end = item["start"], item["end"]
                if not 0 <= start < end <= len(case["text"]):
                    raise ValueError(f"Invalid gold offsets: {case['id']}")
                if case["text"][start:end] != item["text"]:
                    raise ValueError(f"Invalid gold text: {case['id']}")
                if item["label"] not in LABELS:
                    raise ValueError(f"Unsupported gold label: {item['label']}")


def summarize(results, field: str):
    sums = {key: sum(case[field][key] for case in results)
            for key in ("tp", "fp", "fn")}
    sums["precision"] = (sums["tp"] / (sums["tp"] + sums["fp"])
                         if sums["tp"] + sums["fp"] else None)
    sums["recall"] = (sums["tp"] / (sums["tp"] + sums["fn"])
                      if sums["tp"] + sums["fn"] else None)
    return sums


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--prompt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cases", type=Path, default=ROOT / "cases.json")
    parser.add_argument("--dictionary", type=Path, default=ROOT / "dictionary.json")
    parser.add_argument("--threshold", type=float, default=0.4)
    parser.add_argument("--splitter", choices=("default", "spacy-zh"), default="spacy-zh")
    parser.add_argument("--chunk-chars", type=int, default=160)
    parser.add_argument("--overlap", type=int, default=40)
    args = parser.parse_args()
    if not 0 < args.threshold < 1:
        parser.error("threshold must lie between zero and one")
    if args.chunk_chars > 160:
        parser.error("this trial caps chunks at 160 characters to avoid truncation")
    list(chunk_text("validation", args.chunk_chars, args.overlap))
    model_dir = args.model_dir.resolve(strict=True)
    if not model_dir.is_dir():
        parser.error("model-dir must be a local directory")
    cases_data = read_json(args.cases)
    dictionary_data = read_json(args.dictionary)
    validate_gold(cases_data["cases"])
    prompt = args.prompt.read_text(encoding="utf-8-sig")
    deny_network()

    captured_warnings = []
    original_showwarning = warnings.showwarning

    def capture_warning(message, category, filename, lineno, file=None, line=None):
        captured_warnings.append({"message": str(message), "category": category.__name__,
                                  "filename": filename, "lineno": lineno})
        original_showwarning(message, category, filename, lineno, file=file, line=line)

    warnings.showwarning = capture_warning
    warnings.simplefilter("default")

    import torch
    from gliner import GLiNER

    torch.set_num_threads(min(4, os.cpu_count() or 1))
    torch.manual_seed(0)
    try:
        model = GLiNER.from_pretrained(str(model_dir), local_files_only=True,
                                      load_tokenizer=True, map_location="cpu", strict=True)
    except Exception as error:
        write_json(args.output, {"schema_version": "ip_precheck_benchmark_v1",
                                 "status": "model_load_failed",
                                 "model_dir": str(model_dir),
                                 "error_type": type(error).__name__, "error": str(error),
                                 "warnings": captured_warnings})
        raise
    model.to("cpu").eval()
    if args.splitter == "spacy-zh":
        from gliner.data_processing.tokenizer import SpaCyTokenSplitter
        model.data_processor.words_splitter = SpaCyTokenSplitter(lang="zh")
    matcher = DictionaryMatcher(dictionary_data)
    result = {
        "schema_version": "ip_precheck_benchmark_v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running", "copyright_verdict": None,
        "warnings": captured_warnings,
        "limitations": ["小型人工样例，不能证明生产准确率或预测 Seedance 输出版权审核。",
                        "NER 实体、词库命中及创作者引用均不是侵权结论。",
                        "词库未覆盖新名称；无明确名称的描述性相似不在本次实体金标范围。",
                        "字面严格标签和只计跨度的结果均报告，不以宽松结果替代严格结果。"],
        "runtime": {"python": sys.executable, "device": "cpu",
                    "hf_hub_offline": os.environ["HF_HUB_OFFLINE"],
                    "transformers_offline": os.environ["TRANSFORMERS_OFFLINE"],
                    "python_socket_guard": True,
                    "packages": {name: importlib.metadata.version(name)
                                 for name in ("gliner", "spacy", "torch", "transformers")}},
        "settings": {"threshold": args.threshold, "labels": LABELS,
                     "chunk_chars": args.chunk_chars, "overlap": args.overlap,
                     "splitter": args.splitter,
                     "splitter_class": type(model.data_processor.words_splitter).__name__},
        "inputs": {"model_dir": str(model_dir),
                   "cases_sha256": sha256(args.cases),
                   "dictionary_sha256": sha256(args.dictionary),
                   "prompt_path": str(args.prompt.resolve()),
                   "prompt_sha256": sha256(args.prompt),
                   "benchmark_sha256": sha256(Path(__file__))},
        "cases": []}
    write_json(args.output, result)
    with torch.inference_mode():
        for case in cases_data["cases"]:
            ner = infer_ner(model, case["text"], LABELS, args.threshold,
                            args.chunk_chars, args.overlap, case["id"])
            rules = matcher.match(case["text"])
            result["cases"].append({
                **case, "gliner": ner, "dictionary": rules,
                "ner_strict": metric(ner["entities"], case["expected_ner"]),
                "ner_span_only": metric(ner["entities"], case["expected_ner"], labels=False),
                "dictionary_strict": metric(rules["candidates"], case["expected_candidates"]),
                "dictionary_span_only": metric(rules["candidates"],
                                               case["expected_candidates"], labels=False)})
            write_json(args.output, result)
        result["prompt"] = {
            "text": prompt, "gold_annotations": None,
            "gliner": infer_ner(model, prompt, LABELS, args.threshold,
                                 args.chunk_chars, args.overlap, "actual_prompt"),
            "dictionary": matcher.match(prompt)}
    result["summary"] = {field: summarize(result["cases"], field) for field in
                         ("ner_strict", "ner_span_only", "dictionary_strict",
                          "dictionary_span_only")}
    result["status"] = "completed"
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(args.output, result)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()),
                      "summary": result["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
