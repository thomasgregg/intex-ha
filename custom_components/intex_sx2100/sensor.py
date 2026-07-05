"""Sensors: pump status (125), alarm (127), timer/remaining (114), schedules."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntexConfigEntry
from .const import CONF_DEVICE_ID, DP_ALARM, DP_STATE, DP_TIMER
from .coordinator import PumpCoordinator, ScheduleCoordinator
from .entity import device_info
from .schedule import summarize


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors."""
    device_id = entry.data[CONF_DEVICE_ID]
    pump = entry.runtime_data.pump
    entities: list[SensorEntity] = [
        DpSensor(pump, device_id, "Status", DP_STATE, "mdi:pump"),
        DpSensor(pump, device_id, "Alarm", DP_ALARM, "mdi:alert-circle-outline"),
        DpSensor(pump, device_id, "Timer or remaining", DP_TIMER, "mdi:timer-outline"),
    ]
    if entry.runtime_data.schedules is not None:
        entities.append(ScheduleSensor(entry.runtime_data.schedules, device_id))
    async_add_entities(entities)


class DpSensor(CoordinatorEntity[PumpCoordinator], SensorEntity):
    """Expose one local datapoint as a sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PumpCoordinator,
        device_id: str,
        name: str,
        dp: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._dp = dp
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{device_id}_dp{dp}"
        self._attr_device_info = device_info(device_id)

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get(self._dp)


class ScheduleSensor(CoordinatorEntity[ScheduleCoordinator], SensorEntity):
    """Number of active skdl_filter slots; details in attributes."""

    _attr_has_entity_name = True
    _attr_name = "Schedule"
    _attr_icon = "mdi:calendar-clock"
    _attr_native_unit_of_measurement = "slots"

    def __init__(self, coordinator: ScheduleCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{device_id}_schedule"
        self._attr_device_info = device_info(device_id)

    @property
    def native_value(self) -> int | None:
        slots = (self.coordinator.data or {}).get("slots")
        if slots is None:
            return None
        return sum(1 for s in slots if s.get("active"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        slots = data.get("slots") or []
        return {
            "raw": data.get("raw"),
            "slots": slots,
            "summary": [
                f"Slot {i + 1}: {summarize(s)}"
                for i, s in enumerate(slots)
                if s.get("active")
            ],
        }
