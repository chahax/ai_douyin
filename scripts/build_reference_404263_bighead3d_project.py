from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "data/fanqie_promotion/scene_plans/reference_404263_full_workflows_v2.json"
DEFAULT_OUTPUT = ROOT / "data/qa/reference_404263_bighead3d_full_20260826"


STYLE = (
    "Vertical 9:16 premium cinematic stylized 3D adult animation in the established Perfect Lover direction. "
    "All people are unmistakably Chinese adults with elegant oversized heads, large expressive adult eyes, "
    "compact but anatomically adult bodies around 3.2 heads tall, softly modeled skin, detailed hair and cloth, "
    "warm cinematic key light, soft global illumination, shallow depth of field and polished feature-film rendering. "
    "The acting character and face occupy most of the frame; the background stays minimal, blurred and subordinate. "
)

PHONE_ON = (
    "Every visible active smartphone screen faces camera enough to read as a blank, steady blue-white illuminated "
    "rectangle; the screen remains on at constant brightness. No generated text, letters, numbers, icons or interface. "
)

COMMON_AVOID = (
    "child, minor, baby, toddler, mascot, plush toy, stuffed animal, dollhouse, plastic toy, super-deformed body, "
    "giant cartoon mouth, manic expression, photoreal live action, extra person, duplicate person, cloned face, "
    "identity change, hairstyle change, clothing change, extra hand, extra arm, extra limb, missing limb, extra fingers, "
    "fused fingers, broken hand, warped phone, duplicate phone, black active phone screen, dark active phone screen, "
    "screen turning off, screen flicker, generated text, letters, numbers, logo, watermark, body deformation, crouching, "
    "kneeling, dancing, rapid waving, large motion, fast motion, camera shake, pan, tilt, zoom, scene cut, loop, "
    "repeated beginning, frozen interval, exposure pumping, background establishing shot"
)


CHARACTERS = {
    "lin_yue": {
        "name": "林月",
        "role": "young_woman_protagonist",
        "identity_prompt": (
            "adult Chinese woman age 28, oval adult face, warm light-beige skin, large almond-shaped dark-brown eyes, "
            "straight shoulder-length dark hair with a soft side part, slim adult build, coral knitted cardigan over an "
            "ivory ribbed top, dark straight trousers"
        ),
        "invariants": (
            "same oval adult face, same almond dark-brown eyes, same shoulder-length side-parted dark hair, same age 28"
        ),
        "master_seed": 826301,
    },
    "chen_bo": {
        "name": "陈博",
        "role": "male_operator",
        "identity_prompt": (
            "adult Chinese man age 32, narrow angular adult face, medium warm skin, short black side-parted hair, "
            "straight eyebrows, slim adult build, charcoal overshirt over a black crew-neck shirt"
        ),
        "invariants": (
            "same narrow angular adult face, same straight eyebrows, same short side-parted black hair, same age 32"
        ),
        "master_seed": 826302,
    },
    "lao_zhou": {
        "name": "老周",
        "role": "older_male_victim",
        "identity_prompt": (
            "adult Chinese man age 62, gentle weathered square face, salt-and-pepper short hair, subtle eye lines, "
            "kind dark-brown eyes, average adult build, olive-brown cardigan over a muted beige shirt"
        ),
        "invariants": (
            "same gentle weathered square face, same salt-and-pepper short hair, same kind eyes, same age 62"
        ),
        "master_seed": 826303,
    },
    "officer_he": {
        "name": "何警官",
        "role": "police_officer",
        "identity_prompt": (
            "adult Chinese male police officer age 36, calm square adult face, short neat black hair, athletic adult build, "
            "plain solid navy duty uniform with no readable badge, letters or numbers"
        ),
        "invariants": (
            "same calm square adult face, same short neat black hair, same age 36, same plain navy uniform"
        ),
        "master_seed": 826304,
    },
}


SHOT_SPECS = {
    "p01_nightlife_hook": {
        "character_id": "lin_yue",
        "prompt": (
            "Character-first medium full shot of Lin Yue walking between two adult female friends along a warm night street. "
            "Lin Yue is centered and largest, smiling toward her left friend while holding one black phone low in her right hand. "
            "All three women are adults in ordinary contemporary clothes; the street is only soft amber bokeh. " + PHONE_ON
        ),
        "motion": (
            "Start: the three women already walk forward at one natural pace. Action: Lin Yue takes three continuous steps, "
            "briefly turns her eyes toward her left friend, smiles, then returns her gaze to the lit phone held below her waist. "
            "Her free arm swings slightly and both legs keep stepping. End: she is still walking; the phone never changes hands."
        ),
        "speech_direction": "No lip-synced dialogue; natural social smile and listening reactions under narration.",
    },
    "p02_payment_proof": {
        "character_id": "lin_yue",
        "ip_scale": 0.42,
        "prompt": (
            "Tight character reaction shot of Lin Yue on the same warm night street. Her face fills the upper frame and one "
            "upright phone fills the lower foreground, casting blue-white light onto her cheeks. Her eyes widen with surprised "
            "delight and then sharpen with a first hint of doubt. " + PHONE_ON
        ),
        "motion": (
            "Start: Lin Yue looks down at the already lit phone. Action: her eyes widen, eyebrows lift and lips part on one "
            "small breath; the phone rises only two centimeters. End: the smile pauses and she looks up toward someone offscreen."
        ),
        "speech_direction": "No dialogue; one restrained surprise-to-doubt facial progression.",
    },
    "p03_operator_reveal": {
        "character_id": "chen_bo",
        "prompt": (
            "Character-first medium close shot of Chen Bo seated upright behind a narrow worktable with four active black "
            "smartphones arranged in one row. His adult face and right hand dominate the frame; he watches the screens with a "
            "controlled satisfied half-smile. The workroom behind him is dark and blurred, never an establishing view. " + PHONE_ON
        ),
        "motion": (
            "Start: Chen Bo studies the four lit phones. Action: his right index finger completes one small tap on the center phone, "
            "then stops above it; his chin lifts slightly and the half-smile tightens. End: his hand is frozen above the same phone."
        ),
        "speech_direction": "No dialogue; restrained concentration and calculation.",
    },
    "p04_enter_phone_room": {
        "character_id": "lin_yue",
        "prompt": (
            "Over-table character reaction shot from inside the workroom. Lin Yue has just crossed the doorway and is the clear "
            "subject, shown from knees up; several glowing phones form a low foreground leading line toward her shocked adult face. "
            "Chen Bo is a softly focused secondary figure seated to one side. No empty room coverage. " + PHONE_ON
        ),
        "motion": (
            "Start: Lin Yue takes one final step into the room. Action: she slows, scans the nearest glowing phones from left to "
            "right, then fixes her eyes on Chen Bo. End: both feet are planted and her shoulders stiffen; Chen Bo only glances up."
        ),
        "speech_direction": "No dialogue; confusion grows into alarm through eyes and breath.",
    },
    "p05_mood_rupture": {
        "character_id": "chen_bo",
        "prompt": (
            "Tense two-character medium close shot across the glowing phone table. Chen Bo is foreground and dominant, with both "
            "open hands flat beside three active phones; Lin Yue stands behind him in soft focus. His pleasant smile is about to fail. "
            + PHONE_ON
        ),
        "motion": (
            "Start: Chen Bo holds one small social smile. Action: the smile drains gradually, his jaw tightens and eyebrows lower; "
            "only after the smile is gone does he turn his head toward Lin Yue. End: both hands remain flat and never touch a phone."
        ),
        "speech_direction": "No dialogue; controlled friendliness collapses into guarded hostility.",
    },
    "p06_woman_wavers": {
        "character_id": "lin_yue",
        "prompt": (
            "Tight emotional portrait of Lin Yue beside the worktable. Blue-white phone light shapes the underside of her face; "
            "her adult eyes are wet with fear while she tries to regain control. Chen Bo is only an indistinct shoulder at frame edge. "
            + PHONE_ON
        ),
        "motion": (
            "Start: Lin Yue looks at Chen Bo with widened eyes. Action: her lips part, gaze drops to the glowing phones and one shallow "
            "breath raises her shoulders; she swallows and looks back up. End: fear remains but she does not step away."
        ),
        "speech_direction": "No dialogue; fear shifts into a reluctant decision to stay.",
    },
    "p07_learn_pipeline": {
        "character_id": "lin_yue",
        "prompt": (
            "Character-first medium shot of Lin Yue seated upright at the phone table, learning from Chen Bo beside her. Her focused "
            "face, both natural hands and exactly three active phones are clear; Chen Bo points with one open hand from the side. "
            "The background is strongly blurred. " + PHONE_ON
        ),
        "motion": (
            "Start: Lin Yue watches the left phone. Action: she completes one deliberate tap, moves to the center phone and completes "
            "one second tap; Chen Bo points once toward the next phone then withdraws. End: both remain seated with hands separated."
        ),
        "speech_direction": "No dialogue; concentrated eyes and a small confirming nod.",
    },
    "p08_become_proficient": {
        "character_id": "lin_yue",
        "prompt": (
            "Dynamic but controlled character shot of Lin Yue confidently operating a row of four glowing phones. She is centered, "
            "upright and unmistakably adult; Chen Bo reclines as a secondary observer. Her expression has changed from fear to quiet "
            "competence. Minimal dark room. " + PHONE_ON
        ),
        "motion": (
            "Start: Lin Yue focuses on the first phone. Action: she completes two separate tap-and-slide cycles, finishing the first "
            "before starting the second; after each cycle she moves one phone a few centimeters into a completed row. End: she gives "
            "one restrained satisfied smile while Chen Bo remains seated."
        ),
        "speech_direction": "No dialogue; confidence grows through gaze, tempo and a restrained final smile.",
    },
    "p09_elder_transfer": {
        "character_id": "lao_zhou",
        "prompt": (
            "Warm intimate medium close shot of Lao Zhou seated alone at a modest dining table. His gentle weathered adult face is the "
            "subject; he holds one upright phone close enough to illuminate his eyes, while a simple bowl sits low and blurred. "
            + PHONE_ON
        ),
        "motion": (
            "Start: Lao Zhou carefully rereads the lit screen. Action: his thumb hovers, his eyes verify once, then the thumb presses "
            "one time. End: his shoulders lower on a quiet hopeful exhale and the phone remains in the same hand."
        ),
        "speech_direction": "No dialogue; trust and relief, played quietly.",
    },
    "p10_care_vs_indifference": {
        "character_id": "lao_zhou",
        "prompt": (
            "Character-first side close shot of Lao Zhou at the same modest table, holding chopsticks above a plain cold bowl while "
            "the lit phone rests beside it. His tired adult face and conflicted eyes dominate; the room remains soft and empty. "
            + PHONE_ON
        ),
        "motion": (
            "Start: Lao Zhou lifts one small bite. Action: he pauses, eyes shift to the glowing phone, then lowers the chopsticks beside "
            "the bowl without eating. End: he keeps watching the screen, shoulders slightly rounded."
        ),
        "speech_direction": "No dialogue; restrained concern and self-denial.",
    },
    "p11_batch_money_celebration": {
        "character_id": "chen_bo",
        "prompt": (
            "Character-first medium shot in the workroom. Chen Bo leans over four already glowing phones, eyes bright with greed; "
            "Lin Yue watches from the side with a smaller uneasy smile. Faces and hands dominate, not the room. " + PHONE_ON
        ),
        "motion": (
            "Start: Chen Bo checks the row of lit screens. Action: he makes one tap, pushes up halfway from the chair with both feet "
            "planted, and completes one restrained fist celebration near his chest. End: he holds the half-standing pose; Lin Yue "
            "looks from the phones to his face."
        ),
        "speech_direction": "No dialogue; greedy satisfaction contrasted with Lin Yue's hesitation.",
    },
    "p12_fake_illness_setup": {
        "character_id": "lin_yue",
        "prompt": (
            "Character-first intimate medium close shot. Lin Yue lies naturally on a plain sofa under a light blanket, practicing a "
            "sick expression; Chen Bo holds one upright recording phone at the edge of frame. Her face, eyes and one hand at her temple "
            "are the focus. " + PHONE_ON
        ),
        "motion": (
            "Start: Lin Yue looks toward Chen Bo, listening. Action: she closes her eyes gradually, moves one hand from the pillow to "
            "her temple and makes her breathing shallower. End: she holds a believable sick pose while Chen Bo keeps the phone stable."
        ),
        "speech_direction": "No lip-synced dialogue; controlled performance of weakness.",
    },
    "p13_record_fake_material": {
        "character_id": "lin_yue",
        "continuity_from": "p12_fake_illness_setup",
        "prompt": (
            "Continue the exact same sofa shot, characters, clothes, phone and lighting. Lin Yue is still in the practiced sick pose "
            "with her hand at her temple; Chen Bo keeps the same recording phone stable at frame edge. " + PHONE_ON
        ),
        "motion": (
            "Start: Lin Yue holds the sick pose for one beat. Action: after an implied offscreen stop cue she opens her eyes, removes "
            "her hand from her temple, props herself slightly on one elbow and looks toward the recording phone. End: she stays on the sofa."
        ),
        "speech_direction": "No dialogue; the fake weakness drops away into alert self-review.",
    },
    "p14_batch_script_pipeline": {
        "character_id": "lin_yue",
        "prompt": (
            "Character-first over-table medium shot of Lin Yue and Chen Bo operating exactly four active phones. Lin Yue's focused adult "
            "face and two natural hands dominate; completed phones form a neat row, while Chen Bo slides only one phone toward her. "
            + PHONE_ON
        ),
        "motion": (
            "Start: both sit upright with hands separated. Action: Chen Bo slides one phone into reach; Lin Yue completes one copy, "
            "send and push-right path before touching the next phone. End: one completed phone rests in the right row with no crossing hands."
        ),
        "speech_direction": "No dialogue; efficient rehearsed concentration.",
    },
    "p15_male_luxury": {
        "character_id": "chen_bo",
        "prompt": (
            "Stylized luxury character portrait of Chen Bo in the same adult identity, now wearing a fitted black shirt and one gold "
            "chain, standing before soft warm nightlife bokeh. His face and upper torso fill the frame; Lin Yue is a quiet secondary "
            "observer at the edge. No product close-up, no text."
        ),
        "motion": (
            "Start: Chen Bo stands with both feet planted. Action: he lifts the chain once with one hand, raises his chin, turns his torso "
            "only a quarter turn, then lowers the chain. End: he gives one smug smile; his knees remain straight."
        ),
        "speech_direction": "No dialogue; controlled vanity rather than broad comedy.",
    },
    "p16_female_spending_montage": {
        "character_id": "lin_yue",
        "prompt": (
            "Character-first fashion medium full shot of Lin Yue on a softly lit upscale pedestrian street. Her same adult face and hair "
            "are preserved; she now wears a cream tailored coat and carries exactly two shopping bags in her left hand. A shop window "
            "reflection is soft behind her, never a background tour. No receipt, text, logos or panels."
        ),
        "motion": (
            "Start: Lin Yue already walks naturally. Action: she takes exactly two forward steps, stops, looks toward her reflection and "
            "smooths one strand of hair with her empty right hand. End: both bags remain in the same left hand and both feet stay planted."
        ),
        "speech_direction": "No dialogue; growing self-satisfaction with adult restraint.",
    },
    "p17_pool_boast_peak": {
        "character_id": "lin_yue",
        "prompt": (
            "Character-first medium two-shot at a warm rooftop evening gathering. Lin Yue in the cream tailored outfit holds one lit phone "
            "for a selfie; Chen Bo stands beside her showing a watch near his chest. Their adult faces fill most of the frame; two guests "
            "remain tiny blurred silhouettes. No pool establishing shot. " + PHONE_ON
        ),
        "motion": (
            "Start: Lin Yue and Chen Bo face the selfie phone. Action: Chen Bo displays his watch then lowers his wrist; Lin Yue raises the "
            "phone a few centimeters and holds one confident smile. End: both remain side by side with the phone still lit."
        ),
        "speech_direction": "No dialogue; controlled public confidence and vanity.",
    },
    "p18_danger_signal": {
        "character_id": "lin_yue",
        "continuity_from": "p17_pool_boast_peak",
        "prompt": (
            "Continue the exact same rooftop character two-shot, same adult faces, clothes, phone, positions and warm light. Lin Yue's "
            "selfie phone remains upright and steadily illuminated; Chen Bo remains beside her. Background guests stay blurred. " + PHONE_ON
        ),
        "motion": (
            "Start: Lin Yue holds the confident smile. Action: she notices something on the lit phone; the smile fades gradually, her "
            "raised arm lowers first to chest and then waist, and her shoulders tighten. End: Chen Bo turns only his eyes toward her."
        ),
        "speech_direction": "No dialogue; one smooth confidence-to-fear facial change.",
    },
    "p19_pre_raid_pause": {
        "character_id": "officer_he",
        "ip_scale": 0.52,
        "prompt": (
            "Tense low-to-medium character shot at the workroom doorway. Officer He is partly visible and dominant as his hand turns one "
            "door handle; his focused adult face appears above the opening door, and one boot is ready to cross the threshold. The room "
            "behind is blurred, no empty corridor coverage, no readable insignia."
        ),
        "motion": (
            "Start: Officer He's hand already grips the handle. Action: the handle turns once and the door opens enough for one boot to "
            "cross the threshold. End: his focused face remains visible and his weight transfers forward naturally."
        ),
        "speech_direction": "No dialogue; professional focus with minimal motion.",
    },
    "p20_police_entry": {
        "character_id": "officer_he",
        "continuity_from": "p19_pre_raid_pause",
        "prompt": (
            "Continue from the opened workroom doorway. Officer He enters first and a second adult officer remains behind him; Lin Yue and "
            "Chen Bo are visible deeper in the room beside glowing phones. Officer He's face and upper body dominate; no readable badges. "
            + PHONE_ON
        ),
        "motion": (
            "Start: Officer He is already crossing the threshold. Action: he takes one firm step and stops; the second officer follows only "
            "to the doorway. Chen Bo takes one backward step and Lin Yue half-rises then freezes with empty hands away from phones."
        ),
        "speech_direction": "One calm short command-like mouth movement from Officer He; others react silently.",
    },
    "p21_control_and_evidence": {
        "character_id": "officer_he",
        "prompt": (
            "Character-first evidence handling medium close shot. Officer He's serious adult face remains visible above two gloved hands as "
            "he places black phones into one clear evidence bag. Lin Yue and Chen Bo are blurred and still behind him. Confiscated screens "
            "are intentionally dark; no text, labels, insignia or interface."
        ),
        "motion": (
            "Start: Officer He holds the clear bag open. Action: the gloved hands slide exactly two phones into the bag one after another, "
            "then close the zipper once. End: he lifts his gaze toward the detained pair while the sealed bag stays low."
        ),
        "speech_direction": "No dialogue; careful procedural concentration.",
    },
    "p22_victim_meets_truth": {
        "character_id": "lao_zhou",
        "prompt": (
            "Intimate grief medium close shot of Lao Zhou at the same modest dining table. His weathered adult face fills the frame; one "
            "now-dark phone lies beside the untouched bowl. Warm light has cooled and his kind eyes search the blank screen for an answer. "
            "The room remains minimal and blurred."
        ),
        "motion": (
            "Start: Lao Zhou stares at the dark phone. Action: he picks it up with one hand, turns the screen toward himself and presses the "
            "side button once; it does not respond. End: his breathing slows and his eyes lose focus."
        ),
        "speech_direction": "No dialogue; disbelief settles into quiet shock.",
    },
    "p23_denial": {
        "character_id": "lao_zhou",
        "continuity_from": "p22_victim_meets_truth",
        "prompt": (
            "Continue the exact same intimate dining-table shot, same Lao Zhou identity, clothes, dark phone, bowl and cooled warm light. "
            "His face remains dominant and the phone is already held below his chin. No text or interface."
        ),
        "motion": (
            "Start: Lao Zhou holds the dark phone below his chin. Action: he raises it to his right ear along one clean path, leans forward "
            "and waits; his free palm braces the table. End: his lips tremble once and both shoulders sink gradually."
        ),
        "speech_direction": "A barely audible questioning mouth movement near the end, restrained and adult.",
    },
    "p24_grief_landing": {
        "character_id": "lao_zhou",
        "continuity_from": "p23_denial",
        "prompt": (
            "Continue the exact same close shot of Lao Zhou with the same dark phone at his right ear, same clothes, chair, bowl and cooled "
            "warm light. His weathered adult face and unfocused wet eyes dominate; the background is absent in soft blur."
        ),
        "motion": (
            "Start: Lao Zhou waits with the phone at his ear. Action: he quietly asks why there is no reply, stops speaking, releases one "
            "slow breath and lets his gaze become unfocused. End: phone remains at his ear and the final pose holds naturally for 0.6 seconds."
        ),
        "speech_direction": "One short restrained question, then silent grief; natural subtle lip and jaw motion only.",
    },
}


def rounded_frames(duration_seconds: float, fps: int = 25) -> int:
    minimum = max(65, round(duration_seconds * fps))
    return ((minimum - 1 + 7) // 8) * 8 + 1


def build_master_project() -> dict:
    items = []
    for character_id, character in CHARACTERS.items():
        items.append({
            "id": f"master_{character_id}",
            "seed": character["master_seed"],
            "prompt": (
                STYLE
                + "Single-character waist-up identity master portrait against a simple warm neutral studio gradient. "
                + character["identity_prompt"]
                + ". Calm neutral adult expression, direct three-quarter gaze, both natural hands low and mostly out of frame, "
                "no phone, no props, no text, exactly one character."
            ),
        })
    return {
        "project_id": "reference_404263_bighead3d_character_masters_20260826",
        "canvas": {"width": 704, "height": 1248, "fps": 25},
        "keyframe_generation": {
            "checkpoint": "flux1-schnell-fp8.safetensors",
            "width": 704,
            "height": 1248,
            "steps": 4,
            "cfg": 1.0,
            "sampler": "euler",
            "scheduler": "simple",
        },
        "anchor": items[0],
        "shots": items[1:],
    }


def build_story_project(plan: dict) -> dict:
    beats = list(plan["beats"])
    beat_ids = [str(beat["id"]) for beat in beats]
    if beat_ids != list(SHOT_SPECS):
        raise ValueError("shot specs must exactly follow the 24-beat source plan")
    shots = []
    for index, beat in enumerate(beats, start=1):
        beat_id = str(beat["id"])
        spec = dict(SHOT_SPECS[beat_id])
        character_id = str(spec["character_id"])
        character = CHARACTERS[character_id]
        duration = float(beat["duration"])
        shot = {
            "id": beat_id,
            "source_beat_index": index,
            "character_id": character_id,
            "identity_lock": character["invariants"],
            "duration": duration,
            "narration": str(beat.get("narration") or ""),
            "seed": 826400 + index,
            "frames": rounded_frames(duration),
            "i2v_strength": 0.94,
            "ip_scale": float(spec.get("ip_scale", 0.62)),
            "prompt": STYLE + character["identity_prompt"] + ". " + str(spec["prompt"]),
            "motion": str(spec["motion"]),
            "speech_direction": str(spec["speech_direction"]),
            "source_action": str(beat.get("action") or ""),
            "expression_contract": str(beat.get("expression") or ""),
            "gaze_contract": str(beat.get("gaze") or ""),
            "end_pose_contract": str(beat.get("end_pose") or ""),
        }
        if spec.get("continuity_from"):
            shot["continuity_from"] = str(spec["continuity_from"])
        shots.append(shot)
    return {
        "project_id": "reference_404263_bighead3d_full_20260826",
        "title": "404263旧剧本—完美恋人式3D大头成人风完整候选",
        "status": "generation_in_progress_not_publishable",
        "source_plan": str(DEFAULT_PLAN),
        "reference_video_pixels_used": False,
        "reference_video_audio_used": False,
        "canvas": {"width": 704, "height": 1248, "fps": 25},
        "keyframe_generation": {
            "checkpoint": "flux1-schnell-fp8.safetensors",
            "width": 704,
            "height": 1248,
            "steps": 4,
            "cfg": 1.0,
            "sampler": "euler",
            "scheduler": "simple",
        },
        "video_generation": {
            "i2v_strength": 0.94,
            "negative_prompt": COMMON_AVOID,
        },
        "character_bible": CHARACTERS,
        "continuity_policy": {
            "one_performance_shot_per_source_beat": True,
            "legacy_72_cut_quota_enforced": False,
            "character_first_framing": True,
            "active_phone_screens_stay_lit": True,
            "same_scene_chain_from_previous_end_frame": True,
            "chain_ids": [
                "p12_fake_illness_setup>p13_record_fake_material",
                "p17_pool_boast_peak>p18_danger_signal",
                "p19_pre_raid_pause>p20_police_entry",
                "p22_victim_meets_truth>p23_denial>p24_grief_landing",
            ],
        },
        "publish_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
        "shots": shots,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    plan_path = args.plan.resolve()
    output_dir = args.output_dir.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    master_path = output_dir / "character_master_project.json"
    story_path = output_dir / "story_project.json"
    contract_path = output_dir / "style_and_character_contract.json"
    master_path.write_text(json.dumps(build_master_project(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    story = build_story_project(plan)
    story_path.write_text(json.dumps(story, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    contract_path.write_text(
        json.dumps(
            {
                "style": STYLE,
                "active_phone_contract": PHONE_ON,
                "global_avoid": COMMON_AVOID,
                "characters": CHARACTERS,
                "continuity_policy": story["continuity_policy"],
                "release_status": "not_authorized",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"masters": str(master_path), "story": str(story_path), "contract": str(contract_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
