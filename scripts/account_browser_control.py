"""Persist/read account requests. Execution belongs exclusively to backend cron."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description='账号浏览器管控：只入队或查询，不启动浏览器。')
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('queue-prepared-publication')
    prepare.add_argument('path')
    inspect = sub.add_parser('queue-inspect-upload', help='只入队检查固定上传页，不上传文件或修改表单。')
    inspect.add_argument('account_key')
    state = sub.add_parser('status')
    state.add_argument('account_key')
    args = parser.parse_args()
    from src.operations_accounts.browser_control_runtime import queue_prepared_publication, queue_inspect_upload, snapshot
    if args.command == 'queue-prepared-publication':
        value = queue_prepared_publication(args.path)
        value = {name: value.get(name) for name in ('command_id', 'account_id', 'kind', 'state', 'status')}
        value['platform_submission_started'] = False
    elif args.command == 'queue-inspect-upload':
        command = queue_inspect_upload(args.account_key)
        value = {name: command.get(name) for name in ('command_id', 'account_id', 'kind', 'state', 'status')}
        value.update(upload_started=False, platform_submission_started=False, browser_started=False)
    else:
        data = snapshot(args.account_key)
        value = {'account_id': data['account_id'], 'owner': data['owner'],
            'commands': [{key: row.get(key) for key in ('command_id', 'kind', 'state', 'cursor', 'error_code', 'created_at', 'updated_at')}
                         for row in data['commands']]}
        for public, row in zip(value['commands'], data['commands']):
            if row.get('kind') == 'read' and row.get('payload', {}).get('method') == 'inspect_upload_surface':
                public['result'] = row.get('result')
    print(json.dumps(value, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
