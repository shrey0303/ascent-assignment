"""Business-hours arithmetic and SLA target parsing. Pure functions, no I/O.

Calendar (A-01): Monday-Friday, 09:00-18:00 in the workbook timezone, no public holidays.
"N business days" = N x one business day of business time (A-04).
A target without the word "business" ("N hours", "N minutes, 24x7") runs on the wall clock (A-03).
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import config

BUSINESS_DAY_MINUTES = (
    config.BUSINESS_END.hour * 60 + config.BUSINESS_END.minute
    - config.BUSINESS_START.hour * 60 - config.BUSINESS_START.minute
)
CALENDAR_TEXT = (
    f"business hours = Mon-Fri {config.BUSINESS_START:%H:%M}-{config.BUSINESS_END:%H:%M} "
    "(assumption A-01; no document defines them)"
)

_TARGET = re.compile(r"(\d+(?:\.\d+)?)\s*(business\s+)?(minute|min|hour|hr|day)s?", re.I)


@dataclass(frozen=True)
class Target:
    minutes: int
    business: bool  # True: only business time counts. False: wall clock (24x7)
    text: str


def parse_target(text: str | None) -> Target | None:
    match = _TARGET.search(text or "")
    if not match:
        return None
    amount, business, unit = float(match.group(1)), bool(match.group(2)), match.group(3).lower()
    if unit.startswith("min"):
        minutes = amount
    elif unit.startswith("h"):
        minutes = amount * 60
    else:
        minutes = amount * (BUSINESS_DAY_MINUTES if business else 24 * 60)
    if re.search(r"24\s*[x/]\s*7", text, re.I):
        business = False
    return Target(int(minutes), business, text.strip())


def _day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    start = moment.replace(hour=config.BUSINESS_START.hour, minute=config.BUSINESS_START.minute, second=0, microsecond=0)
    end = moment.replace(hour=config.BUSINESS_END.hour, minute=config.BUSINESS_END.minute, second=0, microsecond=0)
    return start, end


def _next_day(moment: datetime) -> datetime:
    return (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def add_business_minutes(start: datetime, minutes: float) -> datetime:
    current, remaining = start, minutes
    while True:
        day_start, day_end = _day_bounds(current)
        if current.weekday() not in config.BUSINESS_DAYS or current >= day_end:
            current = _day_bounds(_next_day(current))[0]
            continue
        current = max(current, day_start)
        available = (day_end - current).total_seconds() / 60
        if remaining <= available:
            return current + timedelta(minutes=remaining)
        remaining -= available
        current = _day_bounds(_next_day(current))[0]


def business_minutes_between(a: datetime, b: datetime) -> int:
    """Business minutes from a to b (negative if b is before a)."""
    if b < a:
        return -business_minutes_between(b, a)
    total, current = 0.0, a
    while current < b:
        if current.weekday() in config.BUSINESS_DAYS:
            day_start, day_end = _day_bounds(current)
            span = (min(b, day_end) - max(current, day_start)).total_seconds()
            total += max(span, 0)
        current = _next_day(current)
    return int(total // 60)


def due_at(start: datetime, target: Target) -> datetime:
    if target.business:
        return add_business_minutes(start, target.minutes)
    return start + timedelta(minutes=target.minutes)
