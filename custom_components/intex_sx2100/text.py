"""Repeat-days editors for the 7 skdl_filter schedule slots.

Accepts ``daily``, ``once`` (dated FP entry) or a comma list like
``mon,wed,fri``. Bit mapping live-verified against the pump.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntexConfigEntry
from .const import CONF_DEVICE_ID
from .coordinator import ScheduleCoordinator
from .entity import device_info
from .schedule import SLOT_COUNT, days_to_text, text_to_days

_DAY = "(mon|tue|wed|thu|fri|sat|sun)"
_PATTERN = rf"^\s*(once|daily|{_DAY}(\s*,\s*{_DAY})*)\s*$"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up repeat-days entities (cloud schedules only)."""
    coordinator = entry.runtime_data.schedules
    if coordinator is None:
        return
    device_id = entry.data[CONF_DEVICE_ID]
    slots = (coordinator.data or {}).get("slots") or []
    async_add_entities(
        SlotDays(coordinator, device_id, i, slots) for i in range(SLOT_COUNT)
    )


class SlotDays(CoordinatorEntity[ScheduleCoordinator], TextEntity):
    """Which days one schedule slot repeats on."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-week"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_pattern = _PATTERN
    _attr_native_min = 0
    _attr_native_max = 27  # len("mon,tue,wed,thu,fri,sat,sun")

    def __init__(
        self,
        coordinator: ScheduleCoordinator,
        device_id: str,
        index: int,
        slots: list[dict[str, Any]],
    ) -> None:
        super().__init__(coordinator)
        self._index = index
        self._attr_name = f"Slot {index + 1} days"
        self._attr_unique_id = f"{device_id}_schedule_{index + 1}_days"
        self._attr_device_info = device_info(device_id)
        active = index < len(slots) and bool(slots[index].get("active"))
        self._attr_entity_registry_enabled_default = active or index < 3

    def _slot(self) -> dict[str, Any] | None:
        slots = (self.coordinator.data or {}).get("slots")
        return slots[self._index] if slots and self._index < len(slots) else None

    @property
    def native_value(self) -> str | None:
        slot = self._slot()
        return None if slot is None else days_to_text(int(slot.get("days", 0)))

    async def async_set_value(self, value: str) -> None:
        try:
            days = text_to_days(value)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_update_slot(self._index, days=days)
