from datetime import datetime
import re


def has_value(value) -> bool:
    return bool(str(value or "").strip())


def normalize_phone(phone: str | None) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return digits[-10:] if len(digits) > 10 else digits


def parse_date(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    patterns = [
        (r"^(\d{1,2})-(\d{1,2})-(\d{4})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?$", "numeric"),
        (r"^(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})$", "text"),
        (r"^(\d{1,2})-([A-Za-z]{3,})-(\d{4})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?$", "text_time"),
    ]
    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

    for pattern, kind in patterns:
        match = re.match(pattern, raw)
        if not match:
            continue
        try:
            if kind == "numeric":
                day, month, year = int(match[1]), int(match[2]), int(match[3])
                hour, minute, second = int(match[4] or 0), int(match[5] or 0), int(match[6] or 0)
                return datetime(year, month, day, hour, minute, second)
            month = months.index(match[2][:3].lower()) + 1
            day, year = int(match[1]), int(match[3])
            hour = int(match[4] or 0) if kind == "text_time" else 0
            minute = int(match[5] or 0) if kind == "text_time" else 0
            second = int(match[6] or 0) if kind == "text_time" else 0
            return datetime(year, month, day, hour, minute, second)
        except (ValueError, IndexError):
            return None

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def start_of_day(date: datetime) -> datetime:
    return datetime(date.year, date.month, date.day)
