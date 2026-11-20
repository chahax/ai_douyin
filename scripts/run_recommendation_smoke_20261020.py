"""One original-identity recovery and one bounded feed smoke, no search/interaction."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from dataclasses import asdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data/recommendation_playback_repair/20261020"
ACCOUNT = "account:9e5f9e75192fa45becb945bc"


def main():
    import psutil
    import urllib.request
    from src.operations_accounts.browser_control_runtime import _submit
    from src.platform_adapter.douyin_playback import PlaybackOptions
    from src.scheduler.account_refresh import request_account_recovery

    if (OUT / "SMOKE_INTENT.json").exists():
        raise RuntimeError("Original smoke exists; inspect it, never repeat")
    deploy = json.loads((OUT / "UNCAPPED_DEPLOYMENT_STOP_INTENT.json").read_text())
    proc = psutil.Process(int((ROOT / "data/logs/streamlit_web.pid").read_text()))
    if proc.pid == 14796 or Path(proc.cwd()).resolve() != ROOT:
        raise RuntimeError("New deployment identity not established")
    if str(ROOT / "scripts/run_streamlit_web.py").lower() not in [s.lower() for s in proc.cmdline()]:
        raise RuntimeError("Unexpected process")
    for name, sha in deploy["sources"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha or (ROOT / name).stat().st_mtime >= proc.create_time():
            raise RuntimeError("Deployment source differs")
    if urllib.request.urlopen("http://127.0.0.1:8501/_stcore/health", timeout=5).status != 200:
        raise RuntimeError("Web not ready")
    with sqlite3.connect((ROOT / "data/account_refresh.db").as_uri() + "?mode=ro", uri=True, timeout=3) as db:
        row = db.execute("SELECT state,revision,recovery_token FROM account_controls WHERE account_uuid=?", (ACCOUNT,)).fetchone()
        if row != ("paused", 56, None):
            raise RuntimeError("Original control changed")
    intent = dict(at=time.time(), pid=proc.pid, created_at=proc.create_time(),
        user_statement="这个不管这个看视频养号是需要保持账号在平台存在日常操作，不限流看一天都没事",
        source="recommend_feed", max_videos=1, per_video_seconds=15, total_minutes=2,
        auto_like=False, auto_comment=False, old_usage_preserved=True,
        scope="one recovery and one bounded feed smoke; pure viewing daily cap removed")
    (OUT / "SMOKE_INTENT.json").write_text(json.dumps(intent, ensure_ascii=False, indent=2), encoding="utf8")
    payload = {"mode": "playback", "options": {
        "authorization_reference": str(OUT / "SMOKE_INTENT.json"), "headless": True,
        "playback_options": asdict(PlaybackOptions(max_videos=1, per_video_seconds=15,
            total_minutes=2, min_relevance_score=60, source="recommend_feed"))}}
    command = _submit("account01", "maintenance", payload, "recommendation-feed:20261020:smoke-1", 100)
    receipt = dict(at=time.time(), command_id=command["command_id"], state=command["state"],
                   request=payload, recovery_requested=False)
    (OUT / "SMOKE_SUBMITTED.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf8")
    # Request a real identity probe, not a fabricated human completion or an
    # automatic replay of the failed smart/search task.
    receipt["recovery_requested"] = request_account_recovery(ACCOUNT, "account01")
    (OUT / "SMOKE_SUBMITTED.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
