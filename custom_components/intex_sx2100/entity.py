"""Shared device info for all entities."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DEVICE_NAME, DOMAIN, MANUFACTURER, MODEL


def device_info(device_id: str) -> DeviceInfo:
    """One device ("Intex Pool") groups all entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        name=DEVICE_NAME,
        manufacturer=MANUFACTURER,
        model=MODEL,
    )
