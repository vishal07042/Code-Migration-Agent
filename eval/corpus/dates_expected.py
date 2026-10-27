"""Reference conversion of eval/corpus/dates.js (verified: static clean, 100% diff)."""

import datetime


def _parse_utc(iso: str) -> datetime.datetime:
    d = datetime.datetime.fromisoformat(iso)
    if d.tzinfo is None:
        return d.replace(tzinfo=datetime.UTC)
    return d.astimezone(datetime.UTC)


def addDays(iso: str, n: int) -> str:
    d = _parse_utc(iso)
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("addDays: integer days expected")
    return (d + datetime.timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def dayOfWeekUtc(iso: str) -> int:
    return (_parse_utc(iso).weekday() + 1) % 7
