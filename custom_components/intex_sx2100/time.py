"""Start-time editors for the 7 skdl_filter schedule slots."""
from __future__ import annotations

from datetime import time as dt_time
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntexConfigEntry
from .const import CONF_DEVICE_ID
from .coordinator import ScheduleCoordinator
from .entity import device_info
from .schedule import SLOT_COUNT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up start-time entities (cloud schedules only)."""
    coordinator = entry.runtime_data.schedules
    if coordinator is None:
        return
    device_id = entry.data[CONF_DEVICE_ID]
    slots = (coordinator.data or {}).get("slots") or []
    async_add_entities(
        SlotStartTime(coordinator, device_id, i, slots) for i in range(SLOT_COUNT)
    )


class SlotStartTime(CoordinatorEntity[ScheduleCoordinator], TimeEntity):
    """Start time of one schedule slot."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-start"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: ScheduleCoordinator,
        device_id: str,
        index: int,
        slots: list[dict[str, Any]],
    ) -> None:
        super().__init__(coordinator)
        self._index = index
        self._attr_name = f"Slot {index + 1} start"
        self._attr_unique_id = f"{device_id}_schedule_{index + 1}_start"
        self._attr_device_info = device_info(device_id)
        self._attr_entity_registry_enabled_default = True

    def _slot(self) -> dict[str, Any] | None:
        slots = (self.coordinator.data or {}).get("slots")
        return slots[self._index] if slots and self._index < len(slots) else None

    @property
    def native_value(self) -> dt_time | None:
        slot = self._slot()
        if slot is None:
            return None
        return dt_time(hour=int(slot["hour"]) % 24, minute=int(slot["minute"]) % 60)

    async def async_set_value(self, value: dt_time) -> None:
        await self.coordinator.async_update_slot(
            self._index, hour=value.hour, minute=value.minute
        )
