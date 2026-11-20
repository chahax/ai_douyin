"""Offline design artifact only. No prepare/run actions, clients, or claims."""
import json
from pathlib import Path
import sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import run_h3_world_source_repair_v2 as source
from scripts import run_h3_screenplay_world_revision_v1 as old
from scripts import creative_resume_dispatch_v3 as io
from src.content_factory import creative_compact_screenplay_draft_v1 as draft

ROOT=old.ROOT.parent/'compact_request_design'


def design_preview():
    brief=io.read(old.BRIEF);casting=source.seed()['fixed_casting'];facts=io.read(source.FACTS)
    core={'setting':'当代普通超市，清晨08:00；桂芳在固定值班室内核生鲜库存/交班记录，马涛从同一敞开门进入。',
        'relationship':'十一年工龄生鲜员工与即将调任的经理，熟悉彼此工作；保留既有脸、发型和衣着。',
        'initial_conflict':'经理想将门店人员调整办成她个人原因离职，她关心是谁让她走及明日仍有何工作安排。',
        'visible_turning_point':'今天报明日班表；她指出删她后明日具体验货环节无人承接，他当面权衡工作损失和书面责任代价。',
        'outcome_boundary':'明确谁提出及次日工作安排、未签离职/协商文件的区别；金额与个案法律结果不定论，纸张实际持有与台词一致。',
        'authority':'assistant concise creative brief under current user revision; not adopted native screenplay'}
    failures=['只给摘要或四段却声称170秒；空对象/数字字符串/后续略。',
        '经理只叫名字或说自己调走，她就无刺激质问；首段延迟开口。',
        '夜景/第二桌/监控/桌上椅/第三人喊话。',
        '桂芳左手压本却同时独立拿打印件；始终坐着又被叫先坐。',
        '今天缺人却无因果改变明日排班；经理起初就不想她签，初始动机反向。',
        '纸张用途/来源/签字/去向混淆，台词说带走但动作留桌。',
        '流程规则替代自然台词，抢反应或长时间空等。']
    prepared=draft.prepare_request(brief,casting,facts,core,failures,io.read(old.PROFILE))
    wire=old.clients.expected_wire_request(prepared['request'])
    original=old.ROOT.parent/'text_final/call_evidence/call_640/request_body.raw'
    compact_bytes=len(json.dumps(wire,ensure_ascii=False,separators=(',',':')).encode())
    return {'schema':draft.VERSION+'/design_preview','status':'offline_format_design_awaiting_explicit_user_authorization',
        'production_dispatch_enabled':False,'provider_calls':0,'new_creative_candidates':0,'new_claims':0,
        'authorization_status':'User response required; suggested/preselected option is not consent',
        'previous_body_capacity_exhausted':True,'last_settled_spend':io.read(old.ROOT.parent/'text_final/STATE.json')['spend'],
        'request':prepared,'expected_wire_preview':wire,
        'request_size_evidence':{'old640_actual_request_body_bytes':original.stat().st_size,
            'compact_expected_wire_utf8_bytes':compact_bytes,'comparison_is_offline_expected_vs_actual':True,
            'full_failed_history_documents_in_new_request':0,'new_request_textual_inputs':['new user brief','fixed actor IDs/SHA/appearance','fixed static scene facts','concise story core','concise known failures']},
        'design_limits':{'no_production_runner':True,'metadata_only_proves_timeline_and_section_presence':True,
            'whole_same_native_text_review_required':True,'no_media_without_separate_valid_scope':True}}


def main():
    value=design_preview();ROOT.mkdir(parents=True,exist_ok=True)
    io.write(ROOT/'REQUEST_PREVIEW.json',value)
    io.write(ROOT/'OUTPUT_SCHEMA_DRAFT.json',draft.output_schema())
    print(json.dumps({'status':value['status'],'provider_calls':0,'new_claims':0,'preview_sha256':io.digest(value),
        'request_size_evidence':value['request_size_evidence']},ensure_ascii=False))


if __name__=='__main__':main()
