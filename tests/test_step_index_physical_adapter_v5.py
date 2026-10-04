"""Mechanical step binding tests; none assert model/creative quality."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator
from scripts import step_index_physical_adapter_v5 as v4
from src.content_factory.creative_stage_contracts import digest
from src.content_factory.creative_workflow_contract import CreativeContractError

RECEIPT=Path("data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/call_048_linear_draft_v5.json")


def identity(context,direction):
    direction["context_sha256"]=digest(context)
    direction["raw_linear_script_sha256"]=digest(context["raw_linear_script"])


def rebind(context,direction,locals_):
    identity(context,direction)
    for i,local in enumerate(locals_):
        local["input_sha256"]=digest(v4.build_local_input(context,direction,locals_[:i]))


def face_case():
    c,d,ls=v4.make_offline_case()
    c["raw_linear_script"]["beats"][0]["steps"][0]["text"]="乙转身朝椅子。"
    c["raw_linear_script"]["beats"][0]["steps"][3]["text"]="乙在可坐侧坐下。"
    d["spatial_contract"]={"seats":[{"seat_id":"E02","access_positions":["桌右"],"required_facing":"E02"}]}
    ls[0]["step_units"][0]["groups"][0]["operations"]=[{"kind":"face","actor":"C02","target":"","value":"E02"}]
    ls[1]["step_units"][1]["groups"][0]["operations"]=[{"kind":"sit","actor":"C02","target":"E02","value":"E02座面"}]
    rebind(c,d,ls)
    return c,d,ls


def readback_args(c,d,ls):
    result=v4.compile_complete(c,d,ls)
    expected=[v4._bind_shot(c,s,l)[2] for s,l in zip(v4._shots(d),ls)]
    v4.attach_scheduler_projection(result["derived_action_plan"],expected)
    return [deepcopy(result["scheduled_execution"]),expected,ls,result["derived_execution_script"],result["schedule_report"]]


class StepPhysicalAdapterTests(unittest.TestCase):
    def setUp(self):
        self.context,self.direction,self.locals=v4.make_offline_case()

    def rejects(self,code,fn):
        with self.assertRaises(CreativeContractError) as caught:fn()
        self.assertIn(code,str(caught.exception))
        return caught.exception

    def test_two_shots_preserve_full_raw_order_and_dialogue_exactly_once(self):
        before=deepcopy((self.context,self.direction,self.locals))
        r=v4.compile_complete(self.context,self.direction,self.locals)
        self.assertEqual(before,(self.context,self.direction,self.locals))
        self.assertEqual(r["source_raw_linear_script"],self.context["raw_linear_script"])
        self.assertEqual([e["anchor"] for e in r["source_trace"]],["G_PLACE","dialogue_0","G_GAZE","G_HOLD","G_TAKE"])
        self.assertEqual([e["source_ref"] for e in r["source_trace"]],
            ["raw_linear_script.beats.0.steps."+str(i) for i in [0,1,2,2,3]])
        self.assertEqual(r["derived_execution_script"]["beats"][0]["dialogue"],[{"speaker":"乙","text":"这次你自己做。"}])
        self.assertEqual(r["derived_execution_script"]["beats"][1]["dialogue"],[])
        self.assertEqual(r["source_narrative_beat_count"],1)
        self.assertEqual(r["execution_shot_count"],2)
        self.assertEqual(r["total_duration_seconds"],8)
        self.assertFalse(r["semantic_approval"])
        self.assertFalse(r["production_ready"])

    def test_two_dialogues_keep_between_action_in_original_order(self):
        c,d,ls=deepcopy((self.context,self.direction,self.locals))
        raw=c["raw_linear_script"]["beats"][0]
        raw["steps"].insert(3,{"kind":"dialogue","speaker":"甲","text":"好，我来。"})
        shot=d["beats"][0]["shots"][0]
        shot["source_step_refs"]=[r["ref"] for r in v4.source_contract.source_catalog(c)]
        shot["performance_requirements"]=d["beats"][0]["shots"][1]["performance_requirements"]
        d["beats"][0]["shots"]=[shot]
        take=ls[1]["step_units"][1]
        take["source_step_ref"]="raw_linear_script.beats.0.steps.4"
        take["groups"][0]["action_ref"]=take["source_step_ref"]
        ls[0]["step_units"]+=ls[1]["step_units"][:1]+[
            {"source_step_ref":"raw_linear_script.beats.0.steps.3","groups":[],
             "dialogue_ref":"raw_linear_script.beats.0.steps.3"},take]
        ls[0]["duration_seconds"]=10
        ls[0]["performance_windows"]=[{"requirement_id":"R1","anchor":"G_HOLD"}]
        ls=ls[:1];rebind(c,d,ls)
        r=v4.compile_complete(c,d,ls)
        self.assertEqual([e["anchor"] for e in r["source_trace"]],
            ["G_PLACE","dialogue_0","G_GAZE","G_HOLD","dialogue_1","G_TAKE"])
        self.assertEqual([e["actual_scheduled_payload"]["script_slot"] for e in r["source_trace"]],
            ["before","dialogue_performance","during","during","dialogue_performance","after"])
        self.assertEqual([m["source_step"] for m in r["source_map"]],raw["steps"])
        self.assertEqual(r["source_unit_coverage_status"],"complete")

    def test_cross_shot_state_comes_from_real_compiler(self):
        r=v4.compile_complete(self.context,self.direction,self.locals)
        first,second=r["storyboard"]["shots"]
        self.assertEqual(json.loads(first["end_state"]),json.loads(second["start_state"]))
        state=v4._state_by_id(second["start_state"],self.context)
        self.assertEqual(state["P01"],{"holder":"none","location":"E01"})
        self.assertEqual(v4._state_by_id(second["end_state"],self.context)["P02"]["holder"],"C02")
        next_input=v4.build_local_input(self.context,self.direction,self.locals[:1])
        self.assertEqual(next_input["start_state"],state)

    def test_cross_shot_after_uses_actual_hold_not_tail(self):
        r=v4.compile_complete(self.context,self.direction,self.locals)
        self.assertEqual(r["performance_checks"],[{"requirement_id":"R1","start":4.25,"end":6.25,
            "relation":"after","subject":"C01","mechanical_check":"passed"}])
        self.assertGreater(r["schedule_report"]["beats"][1]["unused_tail_seconds"],0)
        self.locals[1]["step_units"][0]["groups"][1]["duration_seconds"]=0.5
        self.locals[1]["duration_seconds"]=10
        self.rejects("STEP_WINDOW_TOO_SHORT",lambda:v4.compile_complete(self.context,self.direction,self.locals))

    def test_wrong_hold_subject_rejected(self):
        self.locals[1]["step_units"][0]["groups"][1]["hold_subject"]="C02"
        self.rejects("STEP_WINDOW_SUBJECT",lambda:v4.compile_complete(self.context,self.direction,self.locals))

    def test_missing_reaction_binding_rejected(self):
        self.locals[1]["performance_windows"]=[]
        self.rejects("STEP_WINDOW_COVERAGE",lambda:v4.compile_complete(self.context,self.direction,self.locals))

    def test_action_anchor_cannot_impersonate_full_reaction_hold(self):
        self.locals[1]["performance_windows"][0]["anchor"]="G_TAKE"
        self.rejects("STEP_WINDOW_SOURCE",lambda:v4.compile_complete(self.context,self.direction,self.locals))

    def test_stale_downstream_even_when_physical_state_unchanged(self):
        self.locals[0]["dialogue_performance"]+="，目光先停顿"
        self.rejects("STEP_PHYSICAL_STALE_INPUT",lambda:v4.compile_complete(self.context,self.direction,self.locals))

    def test_stale_raw_text_or_asset_context_rejected(self):
        self.context["raw_linear_script"]["beats"][0]["steps"][1]["text"]="这次请你自己做。"
        self.rejects("STEP_PHYSICAL_SCHEMA_INVALID",lambda:v4.compile_complete(self.context,self.direction,self.locals))

    def test_source_unit_reordering_rejected(self):
        self.locals[0]["step_units"].reverse()
        self.rejects("STEP_LOCAL_COVERAGE",lambda:v4.compile_complete(self.context,self.direction,self.locals))

    def test_empty_action_not_counted_as_source_completion(self):
        self.locals[0]["step_units"][0]["groups"][0]["operations"]=[]
        self.rejects("STEP_ACTION_BINDING",lambda:v4.compile_complete(self.context,self.direction,self.locals))

    def test_no_group_cannot_delete_action_step(self):
        self.locals[0]["step_units"][0]["groups"]=[]
        self.rejects("STEP_ACTION_BINDING",lambda:v4.compile_complete(self.context,self.direction,self.locals))

    def test_wrong_source_action_ref_rejected(self):
        self.locals[1]["step_units"][1]["groups"][0]["action_ref"]="raw_linear_script.beats.0.steps.2"
        self.rejects("STEP_ACTION_BINDING",lambda:v4.compile_complete(self.context,self.direction,self.locals))

    def test_wrong_holder_not_satisfied_by_owner(self):
        self.direction["initial_state"]["P01"]["holder"]="C01"
        self.locals[0]["input_sha256"]=digest(v4.build_local_input(self.context,self.direction,[]))
        self.rejects("PLAN_GROUP_PRECONDITION_INVALID",lambda:v4.compile_prefix(self.context,self.direction,self.locals[:1]))

    def test_valid_holder_can_differ_from_owner(self):
        self.direction["initial_state"]["P01"]["holder"]="C01"
        self.locals[0]["step_units"][0]["groups"][0]["operations"][0]["actor"]="C01"
        rebind(self.context,self.direction,self.locals)
        r=v4.compile_complete(self.context,self.direction,self.locals)
        self.assertTrue(r["physical_state_checked"])
        self.assertEqual(self.context["static_visual_manifest"]["props"][0]["owner_id"],"C02")
        self.assertFalse(r["source_action_semantics_verified"])

    def test_take_then_place_in_same_group_is_not_sequential(self):
        self.direction["initial_state"]["P01"]={"holder":"none","location":"E01"}
        g=self.locals[0]["step_units"][0]["groups"][0]
        g["operations"]=[{"kind":"take","actor":"C02","target":"P01","value":"右手"},
                         {"kind":"place","actor":"C02","target":"P01","value":"E01"}]
        self.locals[0]["input_sha256"]=digest(v4.build_local_input(self.context,self.direction,[]))
        self.rejects("PLAN_GROUP_PRECONDITION_INVALID",lambda:v4.compile_prefix(self.context,self.direction,self.locals[:1]))

    def test_face_projection_preserved_and_next_shot_sit_valid(self):
        c,d,ls=face_case()
        r=v4.compile_complete(c,d,ls)
        face=r["source_trace"][0]
        self.assertEqual(face["physical_operations"],[{"kind":"face","actor":"C02","target":"","value":"E02"}])
        self.assertEqual(face["scheduled_operations"],[])
        self.assertIn("程序派生身体朝向",face["actual_scheduled_payload"]["performance"])
        self.assertIn("face",face["projection_note"])
        first,second=r["storyboard"]["shots"]
        self.assertEqual(v4._state_by_id(first["end_state"],c)["C02"]["facing"],"E02")
        self.assertEqual(json.loads(first["end_state"]),json.loads(second["start_state"]))
        self.assertEqual(v4._state_by_id(second["end_state"],c)["C02"]["posture"],"sitting")
        self.assertEqual(r["schedule_report"]["spatial_checks"][0]["facing"],"E02")

    def test_face_and_sit_same_group_cannot_fix_start_precondition(self):
        c,d,ls=face_case()
        ls[0]["step_units"][0]["groups"][0]["operations"].append(
            {"kind":"sit","actor":"C02","target":"E02","value":"E02座面"})
        ls[0]["input_sha256"]=digest(v4.build_local_input(c,d,[]))
        self.rejects("PLAN_SEAT_ACCESS_INVALID",lambda:v4.compile_prefix(c,d,ls[:1]))

    def test_during_cross_shot_is_explicit_unsupported(self):
        self.direction["beats"][0]["shots"][1]["performance_requirements"][0]["relation"]="during"
        self.rejects("STEP_PHYSICAL_UNSUPPORTED",lambda:v4.validate_direction(self.direction,self.context))

    def test_explicit_parallel_source_rejected_before_tool_build(self):
        self.context["raw_linear_script"]["beats"][0]["execution_requirements"]=[{"kind":"simultaneous_dialogue_action"}]
        self.rejects("STEP_PHYSICAL_UNSUPPORTED",lambda:v4.build_direction_schema(self.context))

    def test_three_dialogues_same_shot_rejected_before_local_request(self):
        raw=self.context["raw_linear_script"]["beats"][0]
        raw["steps"].extend([{"kind":"dialogue","speaker":"甲","text":"我来。"},
                             {"kind":"dialogue","speaker":"乙","text":"好。"}])
        shot=self.direction["beats"][0]["shots"][0]
        shot["source_step_refs"]=[r["ref"] for r in v4.source_contract.source_catalog(self.context)]
        self.direction["beats"][0]["shots"]=[shot]
        identity(self.context,self.direction)
        self.rejects("STEP_PHYSICAL_UNSUPPORTED",lambda:v4.build_local_input(self.context,self.direction,[]))

    def test_partial_local_is_not_full_film(self):
        self.assertFalse(v4.compile_prefix(self.context,self.direction,self.locals[:1])["complete"])
        self.rejects("STEP_LOCAL_COVERAGE",lambda:v4.compile_complete(self.context,self.direction,self.locals[:1]))

    def test_tool_schema_simple_but_local_retains_strict_conditionals(self):
        inp=v4.build_local_input(self.context,self.direction,[])
        schemas=[v4.build_direction_schema(self.context),v4.build_local_schema(inp)]
        for schema in schemas:
            Draft202012Validator.check_schema(schema)
            encoded=json.dumps(schema)
            for keyword in ('"prefixItems"','"allOf"','"if"','"then"'):self.assertNotIn(keyword,encoded)
        self.assertIn('"allOf"',json.dumps(v4._local_schema(self.context,self.direction,"S1")))

    def test_messages_include_full_reference_and_selected_assets_once(self):
        self.context["reference_pack"]={"reference_full_text":"只读完整参考"}
        self.context["selected_assets"]={"C01":"selected/a.png"}
        identity(self.context,self.direction)
        inp=v4.build_local_input(self.context,self.direction,[])
        direct=json.loads(v4.build_direction_messages(self.context)[1]["content"])
        local=json.loads(v4.build_local_messages(inp)[1]["content"])
        self.assertEqual(direct["context"],self.context)
        self.assertEqual(local["local_input"]["context"],self.context)
        self.assertEqual(v4.build_local_messages(inp)[1]["content"].count("只读完整参考"),1)

    def test_scheduler_mutations_are_detected_from_actual_payload(self):
        mutations={
            "operations":lambda args:args[0]["beats"][0]["events"][0]["operations"][0].update(value="E02"),
            "performance":lambda args:args[0]["beats"][0]["events"][0].update(performance="silently changed"),
            "slot":lambda args:args[0]["beats"][0]["events"][0].update(script_slot="after"),
            "duration":lambda args:args[0]["beats"][0]["events"][0].update(end=0.9),
            "dialogue_index":lambda args:args[0]["beats"][0]["events"][1].update(dialogue_index=1),
            "tail_performance":lambda args:args[0]["beats"][0]["events"][-1].update(performance="unbound extra action"),
            "shot_id":lambda args:args[0]["beats"][0].update(beat_id="UNKNOWN")}
        for name,mutate in mutations.items():
            with self.subTest(name=name):
                args=readback_args(self.context,self.direction,self.locals)
                mutate(args)
                self.rejects("STEP_SCHEDULE_ORDER",lambda:v4.readback_schedule(*args))

    def test_scheduler_face_projection_clause_cannot_be_dropped(self):
        c,d,ls=face_case()
        args=readback_args(c,d,ls)
        args[0]["beats"][0]["events"][0]["performance"]=ls[0]["step_units"][0]["groups"][0]["performance"]
        self.rejects("STEP_SCHEDULE_ORDER",lambda:v4.readback_schedule(*args))

    def test_mechanical_success_cannot_approve_false_source_semantics(self):
        self.locals[0]["step_units"][0]["groups"][0]["operations"]=[{"kind":"gaze","actor":"C02","target":"","value":"C01"}]
        rebind(self.context,self.direction,self.locals)
        r=v4.compile_complete(self.context,self.direction,self.locals)
        self.assertEqual(v4._state_by_id(r["storyboard"]["shots"][0]["end_state"],self.context)["P01"]["holder"],"C02")
        self.assertTrue(r["physical_state_checked"])
        for field in ("source_action_semantics_verified","source_reaction_duration_semantics_verified",
                      "face_readability_verified","semantic_approval","production_ready","automatic_media_submit"):
            self.assertFalse(r[field])

    def test_actual_048_offline_schema_reports_missing_not_adopted(self):
        if not RECEIPT.exists():self.skipTest("read-only receipt unavailable")
        before=RECEIPT.read_bytes()
        c,s,r=v4.actual_048_compatibility(RECEIPT)
        self.assertEqual(before,RECEIPT.read_bytes())
        self.assertEqual(r["source_narrative_beats"],14)
        self.assertGreater(r["source_steps"],14)
        self.assertEqual(r["director_generation"],"missing")
        self.assertEqual(r["local_generation"],"missing")
        self.assertFalse(r["physical_compile_attempted"])
        self.assertFalse(r["production_ready"])
        Draft202012Validator.check_schema(s)



def surface_case():
    return v4.make_surface_offline_case()

class SurfaceStepPhysicalAdapterTests(unittest.TestCase):
    def rejects(self,code,fn):
        with self.assertRaises(CreativeContractError) as caught:fn()
        self.assertIn(code,str(caught.exception))

    def test_independent_yellow_slides_across_shots_pink_blue_unchanged(self):
        c,d,ls=surface_case();before=deepcopy((c,d,ls))
        r=v4.compile_complete(c,d,ls)
        self.assertEqual(before,(c,d,ls))
        first,second=r["storyboard"]["shots"]
        start=v4._state_by_id(first["start_state"],c)
        middle=v4._state_by_id(first["end_state"],c)
        final=v4._state_by_id(second["end_state"],c)
        self.assertEqual(middle,v4._state_by_id(second["start_state"],c))
        self.assertEqual(middle["P03_Y"],{"holder":"none","location":"surface:E02:near_fang"})
        self.assertEqual(final["P03_Y"],start["P03_Y"])
        for member in ["P03_P","P03_B"]:
            self.assertEqual(start[member],middle[member]);self.assertEqual(middle[member],final[member])
        self.assertNotIn("P03",middle)
        self.assertEqual(r["source_raw_linear_script"],c["raw_linear_script"])
        self.assertEqual([t["anchor"] for t in r["source_trace"]],
            ["G_SLIDE_NEAR","dialogue_0","G_GAZE","G_HOLD","G_SLIDE_BACK"])
        for index in [0,4]:
            t=r["source_trace"][index]
            self.assertEqual(t["physical_operations"],t["scheduled_operations"])
            self.assertEqual(t["scheduled_operations"][0]["kind"],"slide")
            self.assertEqual(t["scheduler_projection"]["operations"],t["physical_operations"])
            self.assertEqual(t["projection_note"],"identity")
        self.assertFalse(r["semantic_approval"])
        self.assertFalse(r["source_action_semantics_verified"])
        self.assertFalse(r["narrative_estimates_are_actual_execution_windows"])

    def test_held_yellow_cannot_slide(self):
        c,d,ls=surface_case()
        d["initial_state"]["P03_Y"]={"holder":"C02","location":"right_hand"}
        ls[0]["input_sha256"]=digest(v4.build_local_input(c,d,[]))
        self.rejects("PLAN_GROUP_PRECONDITION_INVALID",lambda:v4.compile_prefix(c,d,ls[:1]))

    def test_cross_surface_slide_cannot_hide_take_place(self):
        c,d,ls=surface_case()
        ls[0]["step_units"][0]["groups"][0]["operations"][0]["value"]="surface:E01:near_fang"
        self.rejects("PLAN_GROUP_PRECONDITION_INVALID",lambda:v4.compile_prefix(c,d,ls[:1]))

    def test_registered_chair_is_not_an_explicit_supported_surface(self):
        c,d,ls=surface_case()
        ls[0]["step_units"][0]["groups"][0]["operations"][0]["value"]="surface:E03:seat"
        self.rejects("STEP_PHYSICAL_SCHEMA_INVALID",lambda:v4.compile_prefix(c,d,ls[:1]))

    def test_same_zone_is_not_real_slide(self):
        c,d,ls=surface_case()
        ls[0]["step_units"][0]["groups"][0]["operations"][0]["value"]="surface:E02:lin_center"
        self.rejects("PLAN_GROUP_PRECONDITION_INVALID",lambda:v4.compile_prefix(c,d,ls[:1]))

    def test_collection_id_cannot_impersonate_yellow_member(self):
        c,d,ls=surface_case()
        ls[0]["step_units"][0]["groups"][0]["operations"][0]["target"]="P03"
        self.rejects("STEP_PHYSICAL_SCHEMA_INVALID",lambda:v4.compile_prefix(c,d,ls[:1]))

    def test_two_slides_same_member_in_one_group_conflict(self):
        c,d,ls=surface_case()
        ls[0]["step_units"][0]["groups"][0]["operations"].append(
            {"kind":"slide","actor":"C02","target":"P03_Y","value":"surface:E02:other_side"})
        self.rejects("PLAN_GROUP_OPERATION_CONFLICT",lambda:v4.compile_prefix(c,d,ls[:1]))

    def test_hold_with_slide_remains_rejected(self):
        c,d,ls=surface_case()
        ls[0]["step_units"][0]["groups"][0].update(kind="hold",hold_subject="C02")
        self.rejects("STEP_PHYSICAL_SCHEMA_INVALID",lambda:v4.compile_prefix(c,d,ls[:1]))

    def test_member_initial_surface_is_canonical_even_without_prior_slide(self):
        c,d,ls=surface_case();d["initial_state"]["P03_P"]["location"]="桌上"
        self.rejects("STEP_COMPONENT_INITIAL_STATE",lambda:v4.validate_direction(d,c))

    def test_tampered_member_map_rejected_before_direction_tool(self):
        c,d,ls=surface_case();c["component_registry"]["member_source_map"]["P03_Y"]["source_evidence"]=["浅蓝"]
        self.rejects("STEP_COMPONENT_REGISTRY_INVALID",lambda:v4.build_direction_schema(c))

    def test_registry_effective_manifest_must_match_actual_context(self):
        c,d,ls=surface_case();c["static_visual_manifest"]["props"][-1]["owner_id"]="C02"
        self.rejects("STEP_COMPONENT_REGISTRY_INVALID",lambda:v4.build_direction_schema(c))

    def test_scheduled_slide_mutation_is_detected(self):
        c,d,ls=surface_case();args=readback_args(c,d,ls)
        args[0]["beats"][0]["events"][0]["operations"][0]["kind"]="take"
        self.rejects("STEP_SCHEDULE_ORDER",lambda:v4.readback_schedule(*args))

    def test_stale_member_position_rejected_in_downstream(self):
        c,d,ls=surface_case()
        ls[0]["step_units"][0]["groups"][0]["operations"][0]["value"]="surface:E02:nearer_fang"
        self.rejects("STEP_PHYSICAL_STALE_INPUT",lambda:v4.compile_complete(c,d,ls))

    def test_untimed_raw_stays_unmodified_and_actual_schedule_uses_local(self):
        c,d,ls=surface_case()
        for beat in c["raw_linear_script"]["beats"]:beat.pop("duration_seconds")
        rebind(c,d,ls);before=deepcopy(c["raw_linear_script"])
        r=v4.compile_complete(c,d,ls)
        self.assertEqual(c["raw_linear_script"],before)
        self.assertEqual(r["source_raw_linear_script"],before)
        self.assertTrue(all("duration_seconds" not in b for b in before["beats"]))
        self.assertEqual(r["total_duration_seconds"],sum(l["duration_seconds"] for l in ls))
        self.assertEqual(r["execution_timing_source"],"local_duration_and_actual_schedule_only")
        self.assertFalse(r["narrative_estimates_are_actual_execution_windows"])
        self.assertEqual(r["performance_checks"][0]["end"]-r["performance_checks"][0]["start"],2)


if __name__=="__main__":unittest.main()
