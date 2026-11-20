"""Standard-library-only browser checkpoint helpers shared with the worker.

Importing this module must not initialize platform adapters, settings, logging
or model clients. Persistent profile cookies always take precedence over an
older exported snapshot.
"""

import json
import os
import tempfile
import time
from pathlib import Path


def missing_snapshot_cookies(snapshot: list[dict], current: list[dict]) -> list[dict]:
    key = lambda item: (item.get("name"), item.get("domain"), item.get("path", "/"))
    present = {key(item) for item in current}
    return [item for item in snapshot if key(item) not in present and
            (item.get("expires", -1) in (-1, None) or item["expires"] > time.time())]


def checkpoint_open_login_pages(context, state_path, origins):
    """Atomically save existing pages and cookies, retaining untouched origins."""
    pages = [page for page in context.pages if not page.is_closed()]
    if not pages:
        return False
    cookies = context.cookies()
    try:
        previous = json.loads(Path(state_path).read_text(encoding="utf-8"))
        for entry in previous.get("origins", []):
            if isinstance(entry, dict) and entry.get("origin"):
                origins.setdefault(entry["origin"], entry)
    except (OSError, ValueError, AttributeError):
        pass
    for page in pages:
        for frame in page.frames:
            try:
                entry = frame.evaluate("""() => ({origin: location.origin,
                    localStorage: Object.entries(localStorage).map(([name, value]) => ({name, value}))})""")
            except Exception:
                continue
            if str(entry.get("origin", "")).startswith(("https://", "http://")):
                origins[entry["origin"]] = entry
    target = Path(state_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump({"cookies": cookies, "origins": list(origins.values())}, output, ensure_ascii=False)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True
