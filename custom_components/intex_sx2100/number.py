"""Run-duration editors for the 7 skdl_filter schedule slots."""
from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import EntityCategory, UnitOfTime
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
    entities: list[NumberEntity] = [
        SlotDuration(coordinator, device_id, i, slots) for i in range(SLOT_COUNT)
    ]
    entities.append(FpHours(coordinator, device_id))
    async_add_entities(entities)


class SlotDuration(CoordinatorEntity[ScheduleCoordinator], NumberEntity):
    """Worktime (hours) of one schedule slot."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    # FP-mode one-time runs go up to 48 h (verified in the Intex app).
    _attr_native_max_value = 48
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
        self._attr_name = f"Slot {index + 1} hours"
        self._attr_unique_id = f"{device_id}_schedule_{index + 1}_duration"
        self._attr_device_info = device_info(device_id)
        self._attr_entity_registry_enabled_default = True

    def _slot(self) -> dict[str, Any] | None:
        slots = (self.coordinator.data or {}).get("slots")
        return slots[self._index] if slots and self._index < len(slots) else None

    @property
    def native_value(self) -> int | None:
        slot = self._slot()
        return None if slot is None else int(slot.get("duration", 0))

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_update_slot(self._index, duration=int(value))


class FpHours(CoordinatorEntity[ScheduleCoordinator], RestoreNumber):
    """Duration used by the "Start FP" button (restored across restarts)."""

    # Named "Start FP hours" so the device page's alphabetical ordering puts
    # it right after the "Start FP" button (Pump -> Start FP -> Start FP hours).
    _attr_has_entity_name = True
    _attr_name = "Start FP hours"
    _attr_icon = "mdi:timer-plus"
    _attr_native_min_value = 1
    _attr_native_max_value = 48
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: ScheduleCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{device_id}_fp_hours"
        self._attr_device_info = device_info(device_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (data := await self.async_get_last_number_data()) and data.native_value:
            self.coordinator.fp_hours = int(data.native_value)

    @property
    def native_value(self) -> int:
        return self.coordinator.fp_hours

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.fp_hours = int(value)
        self.async_write_ha_state()
