"""Codec for the pump's ``skdl_filter`` schedule blob.

The blob is a base64-encoded raw value of 7 fixed 8-byte slots. Field order
per the Tuya thing-model ("month date hour minute worktime week control Null"):

* ``month``/``date`` — calendar date for one-time entries (0 for repeating)
* ``hour``/``minute`` — start time
* ``duration`` — worktime in hours
* ``days`` — week bitmask; 0xFF = repeat every day
* ``on`` — control flag (1 = timed run enabled)

Blob format credit: reverse-engineered in Hovborg/intex-pool (MIT).
Pure functions, no Home Assistant imports.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any

SLOT_COUNT = 7
SLOT_SIZE = 8
FIELDS = ("month", "date", "hour", "minute", "duration", "days", "on", "pad")
DAYS_EVERY = 0xFF

# Week byte layout, live-verified against the AGP SAND FILTER PUMP R1
# (Mon-only -> 192, Wed-only -> 144, every day -> 255):
# bit 7 = weekly-repeat flag, bit 6 = Mon ... bit 0 = Sun.
REPEAT_FLAG = 0x80
DAY_BITS = {
    "mon": 0x40,
    "tue": 0x20,
    "wed": 0x10,
    "thu": 0x08,
    "fri": 0x04,
    "sat": 0x02,
    "sun": 0x01,
}


def days_to_text(days: int) -> str:
    """Render the week byte: ``once`` (FP), ``daily``, or ``mon,wed,fri``."""
    days = int(days) & 0xFF
    if days == 0:
        return "once"
    if days == DAYS_EVERY:
        return "daily"
    return ",".join(name for name, bit in DAY_BITS.items() if days & bit)


def text_to_days(text: str) -> int:
    """Parse the week byte, leniently.

    Accepts ``once``, ``daily`` (also ``every day``/``all``), and day lists in
    short or full form with comma/space separators: ``mon,wed``, ``Monday
    Friday``, ``mon + fri``.
    """
    cleaned = text.strip().lower()
    if cleaned in ("once", "never", ""):
        return 0
    if cleaned.replace(" ", "") in ("daily", "everyday", "all"):
        return DAYS_EVERY
    full_names = {
        "mon": "monday", "tue": "tuesday", "wed": "wednesday", "thu": "thursday",
        "fri": "friday", "sat": "saturday", "sun": "sunday",
    }
    days = REPEAT_FLAG
    tokens = [t for t in cleaned.replace("+", " ").replace(",", " ").split() if t]
    for token in tokens:
        abbr = token[:3]
        # valid if it's a day abbreviation or any prefix of the full name
        if abbr in DAY_BITS and full_names[abbr].startswith(token):
            days |= DAY_BITS[abbr]
        elif token in ("daily", "once", "every", "everyday", "all", "day"):
            raise ValueError(
                f"'{token}' can't be combined with other words — use it alone, "
                "or list day names like 'mon,wed,fri'"
            )
        else:
            raise ValueError(
                f"'{token}' is not a day — try 'daily', 'once', or day names "
                "like 'mon,wed,fri' or 'Monday Friday'"
            )
    if days == REPEAT_FLAG:
        raise ValueError(
            "no days given — try 'daily', 'once', or day names like 'mon,wed,fri'"
        )
    return days


def decode_schedules(b64: str | None) -> list[dict[str, Any]]:
    """Decode the base64 blob into exactly 7 slot dicts (never raises)."""
    try:
        data = base64.b64decode(b64) if b64 else b""
    except (binascii.Error, ValueError):
        data = b""
    slots: list[dict[str, Any]] = []
    for i in range(SLOT_COUNT):
        chunk = data[i * SLOT_SIZE : i * SLOT_SIZE + SLOT_SIZE]
        chunk = chunk + bytes(SLOT_SIZE - len(chunk))
        rec: dict[str, Any] = {f: chunk[j] for j, f in enumerate(FIELDS)}
        rec["active"] = any(chunk[:7])
        slots.append(rec)
    return slots


def encode_schedules(slots: list[dict[str, Any]]) -> str:
    """Encode up to 7 slot dicts back into the 56-byte base64 blob."""
    out = bytearray()
    for i in range(SLOT_COUNT):
        rec = slots[i] if i < len(slots) else {}
        out += bytes(int(rec.get(f, 0)) & 0xFF for f in FIELDS)
    return base64.b64encode(bytes(out)).decode()


def mode_of(slot: dict[str, Any]) -> str:
    """``repeating`` when a week mask is set; ``fp_one_time`` for the app's
    dated FP-mode entries (days == 0, month/date set, up to 48 h).

    The ``on`` byte is the app's enable toggle, independent of the mode —
    live-verified against the AGP SAND FILTER PUMP R1 blob 2026-07-05."""
    return "repeating" if slot.get("days") else "fp_one_time"


def summarize(slot: dict[str, Any]) -> str:
    """One-liner like ``Daily 20:50 · 1h · off`` or ``07-04 09:00 · 48h · FP · off``."""
    h, m = int(slot.get("hour", 0)), int(slot.get("minute", 0))
    days = int(slot.get("days", 0))
    if days == DAYS_EVERY:
        when = f"Daily {h:02d}:{m:02d}"
    elif days:
        when = f"{days_to_text(days).title()} {h:02d}:{m:02d}"
    else:
        when = f"{int(slot.get('month', 0)):02d}-{int(slot.get('date', 0)):02d} {h:02d}:{m:02d}"
    fp = "" if days else " · FP"
    state = "on" if slot.get("on") else "off"
    return f"{when} · {int(slot.get('duration', 0))}h{fp} · {state}"


def set_slot(
    slots: list[dict[str, Any]],
    index: int,
    *,
    enabled: bool | None = None,
    hour: int | None = None,
    minute: int | None = None,
    duration: int | None = None,
    days: int | None = None,
    clear: bool = False,
) -> list[dict[str, Any]]:
    """Return a new 7-slot list with slot *index* updated (or cleared)."""
    if not 0 <= index < SLOT_COUNT:
        raise ValueError(f"slot index must be 0-{SLOT_COUNT - 1}")
    out = decode_schedules(encode_schedules(slots))  # normalize to 7 slots
    if clear:
        out[index] = {f: 0 for f in FIELDS} | {"active": False}
        return out
    rec = out[index]
    for key, val in (
        ("on", None if enabled is None else int(enabled)),
        ("hour", hour),
        ("minute", minute),
        ("duration", duration),
        ("days", days),
    ):
        if val is not None:
            rec[key] = int(val) & 0xFF
    rec["active"] = any(rec.get(f, 0) for f in FIELDS[:7])
    return out
