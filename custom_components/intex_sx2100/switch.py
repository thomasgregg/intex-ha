"""Switches: pump (local DP 104) and schedule slot enable (cloud)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntexConfigEntry
from .const import CONF_DEVICE_ID, DP_FILTER_SWITCH, DP_PUMP
from .coordinator import PumpCoordinator, ScheduleCoordinator
from .entity import device_info
from .schedule import SLOT_COUNT, mode_of, summarize


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the pump switch and, with cloud access, slot enable switches."""
    device_id = entry.data[CONF_DEVICE_ID]
    entities: list[SwitchEntity] = [
        PumpSwitch(entry.runtime_data.pump, device_id),
        FilterSwitch(entry.runtime_data.pump, device_id),
    ]
    if (schedules := entry.runtime_data.schedules) is not None:
        slots = (schedules.data or {}).get("slots") or []
        entities.extend(
            SlotEnableSwitch(schedules, device_id, i, slots) for i in range(SLOT_COUNT)
        )
    async_add_entities(entities)


class PumpSwitch(CoordinatorEntity[PumpCoordinator], SwitchEntity):
    """Filtration on/off — the pump's DP 104."""

    _attr_has_entity_name = True
    _attr_name = "Pump"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:pump"

    def __init__(self, coordinator: PumpCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{device_id}_pump"
        self._attr_device_info = device_info(device_id)

    @property
    def is_on(self) -> bool | None:
        value = (self.coordinator.data or {}).get(DP_PUMP)
        return None if value is None else value is True

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_pump(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_pump(False)


class FilterSwitch(CoordinatorEntity[PumpCoordinator], SwitchEntity):
    """filter_switch (DP 106) — official name from the thing model, but the
    physical effect is untested. Disabled by default; enable and test
    carefully with the pump under observation."""

    _attr_has_entity_name = True
    _attr_name = "Filter switch (untested)"
    _attr_icon = "mdi:air-filter"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PumpCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{device_id}_filter_switch"
        self._attr_device_info = device_info(device_id)

    @property
    def is_on(self) -> bool | None:
        value = (self.coordinator.data or {}).get(DP_FILTER_SWITCH)
        return None if value is None else value is True

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_bool(DP_FILTER_SWITCH, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_bool(DP_FILTER_SWITCH, False)


class SlotEnableSwitch(CoordinatorEntity[ScheduleCoordinator], SwitchEntity):
    """Enable/disable one of the 7 skdl_filter schedule slots."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"
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
        self._attr_name = f"Slot {index + 1}"
        self._attr_unique_id = f"{device_id}_schedule_{index + 1}_enabled"
        self._attr_device_info = device_info(device_id)
        self._attr_entity_registry_enabled_default = True

    def _slot(self) -> dict[str, Any] | None:
        slots = (self.coordinator.data or {}).get("slots")
        return slots[self._index] if slots and self._index < len(slots) else None

    @property
    def is_on(self) -> bool | None:
        slot = self._slot()
        return None if slot is None else bool(slot.get("on"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        slot = self._slot()
        if slot is None:
            return None
        return {
            "summary": summarize(slot),
            "mode": mode_of(slot),
            **{k: slot[k] for k in ("hour", "minute", "duration", "days", "month", "date")},
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_update_slot(self._index, enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_update_slot(self._index, enabled=False)
