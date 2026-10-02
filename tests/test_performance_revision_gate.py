import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from src.content_factory.performance_revision_gate import validate_text,validate_accepted,check_call_budget,validate_authorized_failure_cycle

class PerformanceGateTests(unittest.TestCase):
    def fixture(self):
        q={"speaker":"A","text":"hello","mode":"onscreen"}
        script={"characters":[{"name":"A","age":30}],"duration_seconds":5,"beats":[{"id":"B01","duration_seconds":5,"dialogue":[q]}]}
        director={"characters":copy.deepcopy(script["characters"]),"total_seconds":5,"shots":[{"id":"S01","beat_ids":["B01"],"duration_seconds":5,"dialogue":[q],"prompt":"A says hello","reaction_window":{"start_seconds":3,"end_seconds":5}}]}
        return script,director

    def test_authorized_uncapping_preserves_usage_and_other_budget(self):
        state={"calls_started":51,"max_calls":47,"max_total_tokens":900000,"stages":[{"usage":{"total_tokens":584712}}]}
        with self.assertRaisesRegex(ValueError,"call count"):check_call_budget(state)
        state["performance_revision_call_limit_enabled"]=False
        result=check_call_budget(state)
        self.assertEqual(result["calls_started"],51)
        self.assertEqual(result["tokens_used"],584712)
        state["max_total_tokens"]=600000
        with self.assertRaisesRegex(ValueError,"token budget"):check_call_budget(state)


    def test_authorized_shared_video_cycle_is_scoped_to_listed_shots(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp)/"old-ledger.json"
            parent.write_text("{}",encoding="utf-8")
            import hashlib
            cycle={"schema":"authorized_video_revision_cycle/v1","script_family":"blank_cost_20260925","authorized_limit":10,"user_authorization":"允许：新增10次失败上限","authorized_shots":["S03","S06","S10","S12","S16"],"previous_ledger":{"path":str(parent),"sha256":hashlib.sha256(parent.read_bytes()).hexdigest()}}
            ledger={"script_family":"blank_cost_20260925","limit":10}
            self.assertTrue(validate_authorized_failure_cycle(cycle,{"shot_id":"S03"},ledger))
            self.assertFalse(validate_authorized_failure_cycle(cycle,{"shot_id":"S08"},ledger))
            parent.write_text("changed",encoding="utf-8")
            self.assertFalse(validate_authorized_failure_cycle(cycle,{"shot_id":"S03"},ledger))

    def test_valid_text(self):
        self.assertEqual(validate_text(*self.fixture()),{"shots":1,"seconds":5})

    def test_semantic_mutations_blocked(self):
        for mutation in ("duration","identity","dialogue","window","allocation"):
            with self.subTest(mutation=mutation):
                script,d=self.fixture()
                if mutation=="duration":d["shots"][0]["duration_seconds"]=4
                elif mutation=="identity":d["characters"][0]["age"]=60
                elif mutation=="dialogue":d["shots"][0]["dialogue"]=[]
                elif mutation=="window":d["shots"][0]["reaction_window"]["end_seconds"]=6
                else:d["shots"][0]["beat_ids"]=["B02"]
                with self.assertRaises(ValueError):validate_text(script,d)

    def test_stale_review_binding_blocks_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def save(name,obj):
                p=root/name;p.write_text(json.dumps(obj),encoding="utf-8");return {"path":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
            script,d=self.fixture()
            bindings={"script":save("script.json",script),"director":save("director.json",d)}
            bindings["independent_review"]=save("check.json",{"decision":"passed"})
            bindings["review_request"]=save("request.json",{"bindings":{"revised_script":bindings["script"],"director":bindings["director"]}})
            bindings["assistant_review"]=save("assistant.json",{"decision":"passed","script_sha256":bindings["script"]["sha256"],"director_sha256":bindings["director"]["sha256"]})
            save("TEXT_ACCEPTANCE.json",{"decision":"passed","bindings":bindings})
            self.assertEqual(validate_accepted(root)["shots"],1)
            d["shots"][0]["prompt"]="changed after approval"
            save("director.json",d)
            with self.assertRaisesRegex(ValueError,"accepted source changed"):validate_accepted(root)

if __name__=="__main__":unittest.main()
