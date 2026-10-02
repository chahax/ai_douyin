"""Run an explicitly prepared upload batch with visible account browser and receipts."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--batch', required=True)
    args=parser.parse_args()
    batch=Path(args.batch).resolve()
    if not batch.is_relative_to(ROOT/'data/publish_runs'):
        raise ValueError('Batch must be inside project publish_runs')
    job=json.loads(batch.read_text(encoding='utf-8'))
    def update(status, message):
        job.update(status=status, message=message, updated_at=datetime.now(timezone.utc).isoformat())
        temporary=batch.with_suffix('.tmp')
        temporary.write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(batch)
        print(status, message, flush=True)
    def checkpoint():
        while batch.with_suffix('.pause').exists():
            if job['status']!='paused': update('paused','已暂停，等待前端点击继续执行。')
            time.sleep(1)
        if job['status']=='paused':update('running','继续执行。')

    from src.operations_accounts import AccountRuntimeService
    from src.platform_adapter.douyin_adapter import DouyinAdapter
    from src.platform_adapter.models import PublishRequest
    from src.platform_adapter.publish_workflow import PublishWorkflow
    runtime=AccountRuntimeService()
    adapter=None
    try:
        update('running','核对所选账号与平台作品，尚未上传。')
        context=runtime.resolve(job['account_key'])
        if context.account_uuid!=job['account_uuid']:
            raise ValueError('Batch account mismatch')
        class MonitoredWorkflow(PublishWorkflow):
            def _record(self, stage, **details):
                super()._record(stage, **details)
                update('running', '当前视频：'+job.get('current_title','')+'；步骤：'+stage)
                checkpoint()
        with runtime.operation_lease(context, operation='monitored_upload', daily_limit=20, cooldown_seconds=0, lock_seconds=3600):
            adapter=DouyinAdapter(session=context.create_browser_session(headless=False),runtime_context=context)
            adapter.publish_workflow=MonitoredWorkflow(adapter.session)
            checkpoint()
            check=adapter.verify_runtime_identity(force=True)
            if not check.healthy:
                adapter.session.open_page('https://creator.douyin.com/creator-micro/home')
                batch.with_suffix('.pause').touch()
                update('paused','请在账号浏览器完成登录，然后在监控页点击继续执行。'+check.message)
                checkpoint()
                check=adapter.verify_runtime_identity(force=True)
                if not check.healthy:
                    update('blocked',check.message);return
            sync=adapter.sync_videos(page_limit=20)
            if not sync.success:
                update('blocked','平台作品核对失败；先解决创作者中心登录，未开始上传。');return
            existing={v.title.strip() for v in sync.videos}
            job.setdefault('results',[])
            for item in job['items']:
                checkpoint()
                job['current_title']=item['title']
                if item['title'].strip() in existing:
                    update('blocked','平台有同名作品，暂停避免重复提交：'+item['title']);return
                update('running','检查作品管理页同名记录：'+item['title'])
                page=adapter.session.open_page('https://creator.douyin.com/creator-micro/content/manage')
                page.wait_for_timeout(2000)
                if adapter.publish_workflow._page_contains_title(page,item['title']):
                    update('blocked','作品管理页发现同名内容，需人工核对，未重复上传。');return
                result=adapter.publish_video(PublishRequest(video_path=item['video'],title=item['title'],
                    description=item['description'],hashtags=item['hashtags'], visibility='public', ai_generated=True,
                    extra_metadata={'account_uuid':context.account_uuid}))
                job['results'].append({'title':item['title'],'status':result.status,'message':result.message,'post_id':result.post_id,'publish_url':result.publish_url})
                if result.status == 'post_publish_verification_pending':
                    update('blocked', '本条已提交，等待作品展示和声明核验；未重复上传，暂停后续视频。');return
                if not result.success:
                    update('blocked', '已暂停后续视频：'+result.message);return
                update('running','本条已有平台回执，继续下一条。')
            update('completed','批次执行完成，请按各条平台回执区分审核中与已发布。')
    except Exception as exc:
        update('blocked', f'流程停止：{type(exc).__name__}；请查看执行日志。')
        raise
    finally:
        if adapter:
            adapter.close()


if __name__=='__main__':
    main()
