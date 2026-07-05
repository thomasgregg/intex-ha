"""Run-duration editors for the 7 skdl_filter schedule slots."""
from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
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
    """Set up duration entities (cloud schedules only)."""
    coordinator = entry.runtime_data.schedules
    if coordinator is None:
        return
    device_id = entry.data[CONF_DEVICE_ID]
    slots = (coordinator.data or {}).get("slots") or []
    async_add_entities(
        SlotDuration(coordinator, device_id, i, slots) for i in range(SLOT_COUNT)
    )


class SlotDuration(CoordinatorEntity[ScheduleCoordinator], NumberEntity):
    """Worktime (hours) of one schedule slot."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_native_min_value = 0
    _attr_native_max_value = 24
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: ScheduleCoordinator,
        device_id: str,
        index: int,
        slots: list[dict[str, Any]],
    ) -> None:
        super().__init__(coordinator)
        self._index = index
        self._attr_name = f"Schedule {index + 1} duration"
        self._attr_unique_id = f"{device_id}_schedule_{index + 1}_duration"
        self._attr_device_info = device_info(device_id)
        active = index < len(slots) and bool(slots[index].get("active"))
        self._attr_entity_registry_enabled_default = active or index < 3

    def _slot(self) -> dict[str, Any] | None:
        slots = (self.coordinator.data or {}).get("slots")
        return slots[self._index] if slots and self._index < len(slots) else None

    @property
    def native_value(self) -> float | None:
        slot = self._slot()
        return None if slot is None else float(slot.get("duration", 0))

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_update_slot(self._index, duration=int(value))
