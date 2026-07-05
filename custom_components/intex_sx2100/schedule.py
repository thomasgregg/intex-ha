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


def summarize(slot: dict[str, Any]) -> str:
    """One-liner like ``Daily 06:00 · 8h · on``."""
    h, m = int(slot.get("hour", 0)), int(slot.get("minute", 0))
    if slot.get("days") == DAYS_EVERY:
        when = f"Daily {h:02d}:{m:02d}"
    else:
        when = f"{int(slot.get('month', 0)):02d}-{int(slot.get('date', 0)):02d} {h:02d}:{m:02d}"
    state = "on" if slot.get("on") else "off"
    return f"{when} · {int(slot.get('duration', 0))}h · {state}"


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
