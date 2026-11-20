"""Dedicated Fanqie control; writes require an exact, independently bound request."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.operations_accounts.fanqie_account_control import FanqieAccounts, launch_worker, run_owner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "create", "list", "open", "status", "close", "confirm", "catalog", "book", "worker",'promotion-list','promotion-apply','backfill-reconcile','promotion-preflight','promotion-lookup','filled-details','filled-details-controls','backfill-editor-inspect','backfill-new-publication','cleanup-rebind'])
    parser.add_argument('--request',type=Path,help='固定推广申请JSON（含完整意图与授权绑定）')
    parser.add_argument('--observer-request',type=Path,help='仅推广列表的固定只读被动响应诊断请求')
    parser.add_argument('--snapshot-version',choices=['v1','v2'],default='v1',help='显式v2读取原生别名身份；默认保留旧快照')
    parser.add_argument('--ledger-path',type=Path,help='受控项目data业务台账配置，不是任务payload')
    parser.add_argument('--binding-uuid')
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--book-name')
    parser.add_argument('--book-id',help='仅只读推广预检的准确书籍ID')
    parser.add_argument('--lookup-alias',help='只读推广查询的准确别名')
    parser.add_argument('--retained-url',help='仅回填表单观察：详情内必须保留的原已填公开链接')
    parser.add_argument('--lookup-request',type=Path,help='绑定实际控件观察后的一次准确BookID查询请求；省略时仅发现控件')
    parser.add_argument('--locate',action='store_true',help='仅推广预检：当前列表缺书时执行一次准确BookID页面搜索')
    parser.add_argument('--chapters',type=int,default=0,help='0: 全部可读章节（默认）；正数: 显式限制')
    parser.add_argument("--resource")
    parser.add_argument("--command")
    parser.add_argument("--identity")
    parser.add_argument("--confirmed-by")
    parser.add_argument("--douyin-account")
    parser.add_argument("--label", default="番茄小说专属环境")
    args = parser.parse_args()
    if (args.snapshot_version!='v1' or args.observer_request) and args.action!='promotion-list':
        parser.error('native snapshot/observer flags only valid for promotion-list')
    if args.book_id is not None and args.action not in ('promotion-preflight','promotion-lookup','filled-details','filled-details-controls','backfill-editor-inspect'):
        parser.error('--book-id only valid for promotion-preflight/promotion-lookup')
    if (args.lookup_alias is not None or args.lookup_request is not None)and args.action not in ('promotion-lookup','filled-details','filled-details-controls','backfill-editor-inspect'):
        parser.error('lookup fields only valid for promotion-lookup')
    if args.action in ('promotion-lookup','filled-details','filled-details-controls','backfill-editor-inspect')and(not args.book_id or not args.book_name or not args.lookup_alias or args.chapters!=0):
        parser.error('promotion-lookup requires exact book ID/name/alias and reads no chapters')
    if args.action in ('filled-details','filled-details-controls','backfill-editor-inspect') and args.lookup_request is not None:
        parser.error('filled-details accepts no search/write request')
    if args.locate and args.action!='promotion-preflight':
        parser.error('--locate only valid for promotion-preflight')
    if args.action=='promotion-preflight' and (not args.book_id or not args.book_name or args.chapters!=0):
        parser.error('promotion-preflight requires exact --book-id/--book-name and reads no chapters')
    if args.action in ('filled-details-controls','backfill-editor-inspect') and any((args.request,args.binding_uuid,args.manifest_sha256,args.identity,
            args.confirmed_by,args.command,args.douyin_account,args.label!='番茄小说专属环境')):
        parser.error('filled-details-controls accepts only the resource and exact read target')
    if args.action=='backfill-editor-inspect' and not args.retained_url:parser.error('backfill-editor-inspect requires --retained-url')
    if args.retained_url is not None and args.action!='backfill-editor-inspect':parser.error('--retained-url only valid for backfill-editor-inspect')
    accounts = FanqieAccounts(ledger_path=args.ledger_path) if args.ledger_path else FanqieAccounts()
    if args.action == "install":
        result = accounts.install()
    elif args.action == "create":
        if not args.douyin_account:
            parser.error("create requires --douyin-account")
        result = accounts.create(args.label, args.douyin_account)
    elif args.action == "list":
        result = accounts.list()
    elif args.action in {"open", "catalog", "book", "status", "worker",'promotion-list','promotion-apply','backfill-reconcile','promotion-preflight','promotion-lookup','filled-details','filled-details-controls','backfill-editor-inspect','backfill-new-publication','cleanup-rebind'}:
        if not args.resource:
            parser.error("--resource required")
        if args.action == "worker":
            result = run_owner(args.resource,accounts=accounts)
        elif args.action == "status":
            result = {"environment": accounts.get(args.resource), "binding": accounts.bindings().get(args.resource), "command": accounts.latest_command(args.resource)}
        else:
            if args.action=='open':
                from src.operations_accounts.interactive_desktop import require_interactive_desktop
                require_interactive_desktop()
            kind = {'open':'fanqie_login','catalog':'fanqie_catalog','book':'fanqie_book_inspect',
                'promotion-list':'fanqie_promotion_list','promotion-apply':'fanqie_promotion_apply',
                'backfill-reconcile':'fanqie_backfill_reconcile','promotion-preflight':'fanqie_promotion_preflight',
                'promotion-lookup':'fanqie_promotion_lookup','filled-details':'fanqie_filled_details','filled-details-controls':'fanqie_filled_details_controls','backfill-editor-inspect':'fanqie_backfill_editor_inspect',
                'backfill-new-publication':'fanqie_new_publication_backfill','cleanup-rebind':'fanqie_cleanup_rebind'}[args.action]
            extra={}
            if args.action=='promotion-preflight':extra['book_id']=args.book_id
            if args.action in ('promotion-lookup','filled-details','filled-details-controls','backfill-editor-inspect'):
                extra.update(book_id=args.book_id,lookup_alias=args.lookup_alias)
                if args.action=='backfill-editor-inspect':extra['retained_url']=args.retained_url
                if args.lookup_request:
                    import hashlib
                    lookup=args.lookup_request.resolve()
                    extra['lookup_request']={'path':str(lookup),'sha256':hashlib.sha256(lookup.read_bytes()).hexdigest()}
            if args.locate:extra['locate']=True
            if args.snapshot_version=='v2':extra['snapshot_version']='v2'
            if args.observer_request:
                if args.action!='promotion-list':parser.error('--observer-request only valid for promotion-list')
                import hashlib
                observer=args.observer_request.resolve()
                extra['observer_request']={'path':str(observer),'sha256':hashlib.sha256(observer.read_bytes()).hexdigest()}
            if args.action in ('promotion-apply','backfill-new-publication','cleanup-rebind'):
                if not args.request:parser.error(args.action+' requires --request')
                import hashlib
                path=args.request.resolve()
                extra['promotion_request']={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            elif args.request:parser.error('--request only valid for promotion-apply/backfill-new-publication/cleanup-rebind')
            if args.action=='backfill-reconcile':
                if not args.binding_uuid or not args.manifest_sha256:parser.error('backfill-reconcile requires binding and manifest SHA')
                extra.update(binding_uuid=args.binding_uuid,manifest_sha256=args.manifest_sha256)
            elif args.binding_uuid or args.manifest_sha256:parser.error('backfill fields only valid for backfill-reconcile')
            command = accounts.queue(args.resource, kind, book_name=args.book_name,chapters=args.chapters,**extra)
            if args.action in ('backfill-new-publication','cleanup-rebind') and command['kind']!=kind:
                result={'status':'blocked_by_existing_command','command':command,'requested_kind':kind,'worker_launched':False}
            else:
                result = launch_worker(command, accounts)
    else:
        if not args.command:
            parser.error("--command required")
        if args.action == "confirm":
            if not args.identity or not args.confirmed_by:
                parser.error("confirm requires actual --identity and --confirmed-by")
            result = accounts.confirm(args.command, args.identity, args.confirmed_by)
        else:
            result = accounts.request_close(args.command)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
