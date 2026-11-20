"""Export prompt candidates and importable ComfyUI workflows without API calls."""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("director_node", ROOT / "custom_nodes/ai_douyin_director/__init__.py")
node = importlib.util.module_from_spec(spec)
spec.loader.exec_module(node)


def export(card, output):
    prompt, packet = node.compile_card(card)
    inputs = {key: value for key, value in card.items() if key != "schema"}
    api = {"1": {"class_type": "DouyinDirectorCard", "inputs": inputs},
           "2": {"class_type": "DouyinDirectorPreview", "inputs": {
               "prompt": ["1", 0], "review_packet": ["1", 1]}}}
    workflow = {"last_node_id": 2, "last_link_id": 2, "nodes": [
        {"id": 1, "type": "DouyinDirectorCard", "pos": [50, 50], "size": [620, 1400],
         "flags": {}, "order": 0, "mode": 0, "properties": {"Node name for S&R": "DouyinDirectorCard"},
         "inputs": [], "outputs": [
             {"name": "seedance_prompt_candidate", "type": "STRING", "links": [1], "slot_index": 0},
             {"name": "review_packet_json", "type": "STRING", "links": [2], "slot_index": 1}],
         "widgets_values": [card[k] for k in ("shot_id", "duration_seconds", "continuity", *node.FIELDS)]},
        {"id": 2, "type": "DouyinDirectorPreview", "pos": [760, 50], "size": [440, 160],
         "flags": {}, "order": 1, "mode": 0, "properties": {"Node name for S&R": "DouyinDirectorPreview"},
         "inputs": [{"name": "prompt", "type": "STRING", "link": 1},
                    {"name": "review_packet", "type": "STRING", "link": 2}], "outputs": [], "widgets_values": []}],
        "links": [[1, 1, 0, 2, 0, "STRING"], [2, 1, 1, 2, 1, "STRING"]],
        "groups": [], "config": {}, "extra": {}, "version": 0.4}
    output.mkdir(parents=True, exist_ok=False)
    for name, content in {"prompt.txt": prompt, "review.pending.json": packet,
                          "workflow.api.json": json.dumps(api, ensure_ascii=False, indent=2),
                          "workflow.json": json.dumps(workflow, ensure_ascii=False, indent=2)}.items():
        (output / name).write_text(content, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("card", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    export(json.loads(args.card.read_text(encoding="utf-8-sig")), args.output)
