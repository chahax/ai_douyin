"""Synthetic contracts and dispatch-stop fixtures; never provider/media calls."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import json
import socket
import httpx

from src.content_factory import creative_screenplay_world_v1 as m
from scripts import creative_resume_dispatch_v3 as io
from scripts import run_h3_screenplay_world_revision_v1 as runner
from scripts import creative_m31_screenplay_role_clients_v1 as screenplay_clients
from scripts import creative_m31_flash_role_clients_v1 as old_clients
from scripts.creative_call_evidence_v1 import CallEvidenceJournal


def fixtures():
    brief={'fixture':True}; cast={c:{'name':name,'asset_id':f'test.{c}','sha256':'1'*64,'appearance_and_clothing':'fixture clothing'}
        for c,name in [('C01','周桂芳'),('C02','马涛')]}
    world={'schema':m.VERSION+'/world','brief_sha256':m.digest(brief),'title':'synthetic fixture',
        'story_question':'fixture','time_of_day':'清晨','continuous_time_basis':'连续','environment_light_sound':'室内灯光',
        'space_map':[{'zone_id':'room','description':'室内'},{'zone_id':'door','description':'门框'}],
        'spatial_connections':[{'from_zone':'door','to_zone':'room','relation':'相通'}],
        'characters':[{'id':c,**cast[c],'reference_asset_id':cast[c]['asset_id'],'reference_sha256':cast[c]['sha256'],
                       'motivation':'fixture','pressure_and_cost':'fixture','relationship':'同事','initial_work_or_entry':'fixture'} for c in m.CAST],
        'props':[{'prop_id':'P1','name':'纸','purpose':'fixture','initial_custody':'桌面','final_intended_custody':'桌面'}],
        'dramatic_arc':[{'stage':str(i),'stimulus':'fixture','choice':'fixture','consequence':'fixture'} for i in range(3)],
        'legal_guardrails':['不推断法律结论'],'ending_boundary':'fixture'}
    for c in world['characters']:
        c.pop('asset_id');c.pop('sha256')
    state={'characters':{c:{'zone_id':'room' if c=='C01' else 'door','pose_hands':'手持工具','expression_eyeline':'看对方'} for c in m.CAST},'props':{'P1':'桌面'}}
    segments=[]
    for index in range(10):
        segments.append({'id':f'S{index+1:02}','start_seconds':15*index,'duration_seconds':15.0,
            'story_time':'清晨','location_zone_id':'room','environment_light_sound':'室内灯光','previous_causal_link':'fixture前因',
            'next_causal_link':'fixture后果','emotional_focus':'桂芳','start_state':deepcopy(state),'end_state':deepcopy(state),
            'events':[{'start_s':0,'end_s':15,'characters':{c:{'action':'fixture动作','expression':'fixture神情','eyeline':'对方'} for c in m.CAST},
                'dialogue':[{'speaker':'C02','text':'桂芳。','start_s':0,'end_s':1},
                            {'speaker':'C01','text':'怎么了。','start_s':1.5,'end_s':3}], 'prop_change':'无变化'}],
            'dramatic_change':'fixture变化'})
    body={'schema':m.VERSION+'/screenplay','brief_sha256':m.digest(brief),'world_sha256':m.digest(world),
          'title':'fixture','premise':'fixture','total_duration_seconds':150,'segments':segments}
    check={'status':'pass','reason':'fixture only; no quality claim','quotes':['fixture动作'],'required_revision':''}
    review={'schema':m.VERSION+'/full_review','brief_sha256':m.digest(brief),'world_sha256':m.digest(world),'script_sha256':m.digest(body),
        'world_and_story_checks':{k:deepcopy(check) for k in m.CHECKS},'segments':{s['id']:deepcopy(check) for s in segments},
        'overall_status':'pass','whole_revision_instructions':''}
    return brief,cast,world,body,review


class ScreenplayWorldContracts(unittest.TestCase):
    def setUp(self):self.brief,self.cast,self.world,self.body,self.review=fixtures()

    def test_native_source_identities_and_normal_contract(self):
        self.assertTrue(m.validate_world(self.world,self.brief,self.cast)['valid'])
        self.assertTrue(m.validate_script(self.body,self.brief,self.world)['valid'])
        result=m.validate_review(self.review,self.brief,self.world,self.body)
        self.assertTrue(result['accepted']);self.assertFalse(result['creative_quality_passed'])
        mutated=deepcopy(self.world);mutated['characters'][0]['reference_sha256']='2'*64
        with self.assertRaises(Exception):m.validate_world(mutated,self.brief,self.cast)

    def test_event_holes_and_undescribed_tail_rejected_but_covered_overlap_allowed(self):
        segment=self.body['segments'][0];event=segment['events'][0]
        event['end_s']=5
        later=deepcopy(event);later.update(start_s=6,end_s=15,dialogue=[]);segment['events'].append(later)
        self.assertIn('gap',' '.join(m.validate_script(self.body,self.brief,self.world)['diagnostics']))
        later['start_s']=4
        self.assertTrue(m.validate_script(self.body,self.brief,self.world)['valid'])
        later['end_s']=14
        self.assertIn('tail',' '.join(m.validate_script(self.body,self.brief,self.world)['diagnostics']))

    def test_boundary_state_and_opening_prop_custody_cannot_jump(self):
        self.body['segments'][1]['start_state']['characters']['C01']['zone_id']='door'
        result=m.validate_script(self.body,self.brief,self.world)
        self.assertFalse(result['valid']);self.assertIn('previous original end_state',' '.join(result['diagnostics']))
        self.body['segments'][0]['start_state']['props']['P1']='凭空改成口袋'
        self.assertIn('opening prop',' '.join(m.validate_script(self.body,self.brief,self.world)['diagnostics']))

    def test_immediate_entry_reply_duration_and_speed_are_necessary_checks(self):
        event=self.body['segments'][0]['events'][0]
        event['dialogue'][0]['start_s']=.5
        event['dialogue'][1]['speaker']='C02'
        result=m.validate_script(self.body,self.brief,self.world)
        self.assertIn('immediately',' '.join(result['diagnostics']));self.assertIn('actual reply',' '.join(result['diagnostics']))
        event['dialogue'][0]['text']='字'*20
        self.assertIn('4.2',' '.join(m.validate_script(self.body,self.brief,self.world)['diagnostics']))
        self.body['segments'][0]['duration_seconds']=14
        self.assertIn('must be15.0',' '.join(m.validate_script(self.body,self.brief,self.world)['diagnostics']))

    def test_review_wrong_scope_quotes_and_inconsistent_verdict_refuse(self):
        self.review['segments']['S01']['quotes']=['这句话并不存在']
        self.assertFalse(m.validate_review(self.review,self.brief,self.world,self.body)['valid'])
        self.review['segments']['S01']['quotes']=['fixture动作']
        self.review['segments']['S01'].update(status='fail',required_revision='完整稿重写')
        self.assertFalse(m.validate_review(self.review,self.brief,self.world,self.body)['valid'])
        self.review['overall_status']='fail'
        result=m.validate_review(self.review,self.brief,self.world,self.body)
        self.assertTrue(result['valid']);self.assertFalse(result['accepted'])

    def test_review_hash_binding_and_user_readable_projection(self):
        wrong=deepcopy(self.body);wrong['title']='another body'
        with self.assertRaises(Exception):m.validate_review(self.review,self.brief,self.world,wrong)
        text=m.render_script(self.body,self.world)
        self.assertIn('核心问题：',text);self.assertIn('人物与关系',text);self.assertIn('段尾状态：',text)
        self.assertNotIn('"dramatic_arc"',text)


class ScreenplayRunnerGuards(unittest.TestCase):
    def test_installed_sdk_serializes65536_and_exact_original_wire_before_one_send(self):
        profile=io.read(runner.PROFILE)
        prepared=m.request('complete_script',profile,'fixture','fixture',{'type':'object','properties':{'x':{'type':'string'}},'required':['x'],'additionalProperties':False})
        request=prepared['request'];sent=[]
        fixtures_dir=runner.PROJECT/'data/qa/h3_screenplay_world_20261015/fixtures';fixtures_dir.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=fixtures_dir) as directory:
            evidence=CallEvidenceJournal(Path(directory)/'call',{'ordinal':1,'label':'offline_cap','request_sha256':io.digest(request),
                'source_binding_sha256':'fixture','role':'writer','model':request['model']})
            def handler(outgoing):
                sent.append(json.loads(outgoing.read()))
                self.assertEqual(json.loads((evidence.root/'request_body.raw').read_bytes()),sent[0])
                return httpx.Response(200,json={'id':'fixture-id','model':request['model'],'choices':[{'index':0,'finish_reason':'tool_calls',
                    'message':{'role':'assistant','content':None,'tool_calls':[{'id':'tool','type':'function','function':{'name':old_clients.TOOL_NAME,'arguments':'{"x":"fixture"}'}}]}}],
                    'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15},'base_resp':{'status_code':0}})
            def factory(**kwargs):return httpx.Client(transport=httpx.MockTransport(handler),**kwargs)
            client=screenplay_clients.ScreenplayRoleClients(expected_request=request,http_client_factory=factory)
            with patch.object(old_clients,'role_config',return_value=SimpleNamespace(api_key='offline-only',model='MiniMax-M3',base_url='https://api.minimaxi.com/v1')),patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')):
                result=client.call('writer',request['messages'],max_tokens=65536,temperature=.4,thinking='adaptive',structured_schema=request['structured_schema'],evidence=evidence)
            self.assertEqual(len(sent),1);self.assertEqual(sent[0]['max_completion_tokens'],65536)
            self.assertEqual(result.metadata['total_tokens'],15)
            self.assertEqual(sent[0],screenplay_clients.expected_wire_request(request))

    def test_independent65536_body_wire_and_old_limit_remain_separate(self):
        brief,cast,world,body,review=fixtures()
        profile=io.read(runner.PROFILE)
        prepared=m.prepare_script(brief,world,{'fixture':True},profile)
        request=prepared['request']
        wire=screenplay_clients.expected_wire_request(request)
        self.assertEqual(wire['max_completion_tokens'],65536)
        client=screenplay_clients.ScreenplayRoleClients(expected_request=request)
        self.assertEqual(client._wire,wire)
        self.assertEqual(client._request,request)
        self.assertEqual(old_clients.WRITER_MAX_COMPLETION_TOKENS,16000)
        with self.assertRaises(Exception):old_clients.expected_wire_request(request)
        for cap in (16000,32000,65537):
            changed=deepcopy(request);changed['parameters']['max_completion_tokens']=cap
            with self.assertRaises(Exception):screenplay_clients.expected_wire_request(changed)
        changed=deepcopy(request);changed['stage']='goal_plan'
        with self.assertRaises(Exception):screenplay_clients.expected_wire_request(changed)

    def test_review_preview_identity_ignores_only_display_timestamp_and_self_hash(self):
        a={'created_at':'a','data':1};b={'created_at':'b','data':1,'primary_review_identity':'display'}
        self.assertEqual(runner.preview_identity(a),runner.preview_identity(b))
        b['data']=2;self.assertNotEqual(runner.preview_identity(a),runner.preview_identity(b))

    def test_unreviewed_prepare_does_not_claim_or_dispatch(self):
        with patch.object(runner,'preview',return_value={'test':1}),patch.object(runner.policy,'new_claim',side_effect=AssertionError('claim forbidden')):
            with self.assertRaisesRegex(ValueError,'primary-reviewed'):runner.prepare('wrong')

    def test_unknown_native_stops_after_original_call_and_run_cannot_restart(self):
        class Runtime:
            ledger=None
            def summary(self):return {'fixture':True}
        fixtures_dir=runner.PROJECT/'data/qa/h3_screenplay_world_20261015/fixtures'
        fixtures_dir.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=fixtures_dir) as directory:
            root=Path(directory);rt=Runtime();rt.ledger=root/'CALL_LEDGER.json'
            io.write(rt.ledger,{'calls':[]});io.write(root/'PREVIEW.json',{'brief':{},'seed':{},'first_request':{}})
            receipt={'ordinal':637,'status':'outcome_unknown','request':{'model':'test'},'response_metadata':{}}
            with patch.object(runner,'ROOT',root),patch.object(runner,'guard',return_value=True),patch.object(runner,'runtime',return_value=rt),patch.object(runner,'invoke',return_value=receipt) as invoke:
                result=runner.run();self.assertEqual(result['status'],'halt_interface_or_unknown');self.assertEqual(invoke.call_count,1)
                with self.assertRaises(FileExistsError):runner.run()


if __name__=='__main__':unittest.main()
