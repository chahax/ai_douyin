"""Prepare a backfill workbook from an original verified publication; no upload."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.services.fanqie_backfill_workflow import BackfillBinding, prepare


def main(argv=None):
    parser = argparse.ArgumentParser(description="准备番茄回填文件；不打开浏览器、不上传、不提交")
    parser.add_argument("--binding", required=True, help="绑定JSON，包含原发布command_id及书籍/账号信息")
    parser.add_argument("--browser-db", default=str(ROOT/"data/account_browser_control.db"))
    parser.add_argument("--template", required=True, help="从番茄页面下载的原始xlsx模板")
    parser.add_argument("--output", required=True, help="新的输出目录（不覆盖）")
    args = parser.parse_args(argv)
    binding = BackfillBinding(**json.loads(Path(args.binding).read_text(encoding="utf-8")))
    result = prepare(binding, args.browser_db, args.template, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
