"""Safe console output helpers for Windows GBK environments.

On Windows the console codec is typically GBK (cp936), which cannot
encode all Unicode characters.  ``print(json.dumps(..., ensure_ascii=False))``
raises ``UnicodeEncodeError`` when the data contains characters outside
the GBK repertoire (e.g.  certain CJK Extension-B characters, emoji,
decorative symbols like  U+2795 HEAVY PLUS SIGN).

This module provides a drop-in alternative that falls back to ASCII-only
JSON escapes when the console codec cannot represent the original text.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def safe_print_json(data: Any, **json_kwargs: Any) -> None:
    """Print *data* as JSON to stdout, safe on Windows GBK consoles.

    Defaults match the existing project convention: ``ensure_ascii=False``,
    ``indent=2``.  Extra keyword arguments are forwarded to ``json.dumps``.

    On first failure the same payload is serialized with
    ``ensure_ascii=True``. JSON consumers reconstruct the original Unicode,
    while legacy GBK consoles receive only representable ASCII bytes.
    """
    json_kwargs.setdefault("ensure_ascii", False)
    json_kwargs.setdefault("indent", 2)
    text = json.dumps(data, **json_kwargs)

    try:
        print(text)
    except UnicodeEncodeError:
        fallback_kwargs = dict(json_kwargs)
        fallback_kwargs["ensure_ascii"] = True
        print(json.dumps(data, **fallback_kwargs))
