"""Small parsing helpers shared by the site parsers."""

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

_NUM_RE = re.compile(r"\d[\d.]*")
_ROME = ZoneInfo("Europe/Rome")


def to_int(value: Any) -> Optional[int]:
    """'€ 209.000' -> 209000, '144 m²' -> 144, 3 -> 3, None/'' -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    m = _NUM_RE.search(str(value).replace("\xa0", " "))
    if not m:
        return None
    digits = m.group(0).replace(".", "")
    return int(digits) if digits and int(digits) > 0 else None


def to_float(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f != 0 else None


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parse site timestamps to aware UTC; naive values are Italian local time."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_ROME)
        return dt.astimezone(timezone.utc)
    return None


def script_json(html: str, script_id: str) -> Any:
    m = re.search(rf'<script[^>]*id="{re.escape(script_id)}"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = re.sub(r"[ \t]+", " ", str(value)).strip()
    return text or None


def clean_title(value: Any) -> Optional[str]:
    """'via Roma,, Centro, Cascina' -> 'via Roma, Centro, Cascina'; drops trailing commas."""
    text = clean_text(value)
    if text is None:
        return None
    text = re.sub(r"\s*,(\s*,)+", ",", text)
    return text.strip(" ,") or None


def dig(obj: Any, *path: Any, default: Any = None) -> Any:
    """Safe nested lookup: dig(d, 'a', 0, 'b')."""
    cur = obj
    for key in path:
        try:
            cur = cur[key]
        except (KeyError, IndexError, TypeError):
            return default
        if cur is None:
            return default
    return cur
