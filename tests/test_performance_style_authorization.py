import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from src.content_factory.performance_revision_gate import visual_preview_allowed

class VisualAuthorizationTests(unittest.TestCase):
    def test_scoped_authorization_and_known_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            auth=root/"authorization.json"
            auth.write_text(json.dumps({"authorization":"允许本片先完成画面，声音口型留待整片审查","series_directory":str(root),"story_sha256":"story","style":"photorealistic_cinema"}),encoding="utf-8")
            binding={"path":str(auth),"sha256":hashlib.sha256(auth.read_bytes()).hexdigest()}
            plan={"visual_first_authorization":binding,"first_frame":{"path":str(root/"tail.png")},"sources":{"screenplay":{"path":"script.json","sha256":"story"}}}
            review={"decision":"visual_passed_audio_pending","checks":{k:True for k in ("identity","spatial_layout","props_and_hands","action_pace","cut_continuity","visual_storytelling")}}
            review["checks"].update(voice=None,speech_pace=None,lip_sync=None)
            self.assertTrue(visual_preview_allowed(plan,review,plan))
            for key in review["checks"]:
                bad=deepcopy(review);bad["checks"][key]=False
                self.assertFalse(visual_preview_allowed(plan,bad,plan),key)
            bad=deepcopy(plan);bad["sources"]["screenplay"]["sha256"]="other"
            self.assertFalse(visual_preview_allowed(bad,review,bad))
            bad=deepcopy(plan);bad.pop("visual_first_authorization")
            self.assertFalse(visual_preview_allowed(plan,review,bad))
            auth.write_text("{}",encoding="utf-8")
            with self.assertRaises(ValueError):
                visual_preview_allowed(plan,review,plan)

if __name__=="__main__":
    unittest.main()
