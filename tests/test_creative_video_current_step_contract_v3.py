
import copy
from pathlib import Path
import pytest
from src.content_factory.creative_segment_execution import read
from src.content_factory.creative_video_current_step_contract_v3 import (
 build_contract,render_offline_prompt,validate_contract,require_production_ready)
ROOT=Path(__file__).resolve().parents[1]
DEFS=read(ROOT/"data/video_generation/legal_trend_20261008/remaining_batch_v1/BATCH_MANIFEST.json")["segments"]
def get(sid):return next(d for d in DEFS if d["segment_id"]==sid)
def test_paper_turn_contains_no_future_signing_invitation():
 c=build_contract(get("LG01"));p=render_offline_prompt(c)
 assert "看完没问题就签一下" not in p
 assert "完全没有对白" in p
 assert all(s["spoken_text"] is None for s in c["steps"])
@pytest.mark.parametrize("sid",["LG11","LG12","LG13"])
def test_badge_action_excluded_from_earlier_fragments(sid):
 p=render_offline_prompt(build_contract(get(sid)))
 assert "挂回" not in p
 assert "工牌位置：小林桌角" in p
def test_badge_action_occurs_only_in_current_badge_step():
 p=render_offline_prompt(build_contract(get("LG14")))
 assert p.count("挂回脖子上")==1
 assert "完全没有对白" in p
def test_split_speech_cues_never_reintroduce_other_chunk_words():
 a=render_offline_prompt(build_contract(get("LG11")))
 b=render_offline_prompt(build_contract(get("LG12")))
 assert "对不上我就先不签" not in a
 assert b.count("对不上我就先不签")==1
 assert "我理解你赶时间" not in b
def test_all_original_phase_durations_and_source_text_preserved():
 for d in DEFS:
  c=build_contract(d)
  for s,p in zip(c["steps"],d["pieces"]):
   r=p["row"]
   assert sum(s["phase_seconds"].values())==pytest.approx(r["end"]-r["start"])
   assert (s["spoken_text"] if r["source_kind"]=="dialogue" else p["row"]["original_text"])==r["original_text"]
   assert s["start_state"]==r["start_state"] and s["end_state"]==r["end_state"]
@pytest.mark.parametrize("mutate",[
 lambda c:c["cast"].append({"role_id":"third","name":"第三人"}),
 lambda c:c["captions"].update(subtitles=True),
 lambda c:c["steps"][0].update(current_action="拿起工牌挂回脖子"),
 lambda c:c["steps"][0]["end_state"].update(badge_location="xiaolin_neck"),
])
def test_invented_actor_caption_action_state_rejected(mutate):
 d=get("LG12");c=build_contract(d);mutate(c)
 with pytest.raises(ValueError):validate_contract(c,d)
def test_missing_active_delivery_contract_blocks_production():
 for d in DEFS:
  c=build_contract(d)
  with pytest.raises(ValueError,match="offline proposal"):
   require_production_ready(c)
  assert c["production_ready"] is False



def test_image_tail_never_claims_bound_audio_identity():
 c=build_contract(get("LG12"))
 assert c["audio_identity"]["reference_bound"] is False
 assert any("voice binding" in x for x in c["production_blockers"])
 assert "及声线保持一致" not in render_offline_prompt(c)
