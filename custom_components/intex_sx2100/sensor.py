"""Sensors: status, alarm, decoded error code, working time, schedules."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntexConfigEntry
from .const import (
    CONF_DEVICE_ID,
    DP_ALARM,
    DP_ERROR_BITMAP,
    DP_STATE,
    DP_WORKING_TIME,
    decode_error_bits,
)
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
        ModeSensor(pump, device_id),
        DpSensor(pump, device_id, "Alarm", DP_ALARM, "mdi:alert-circle-outline"),
        ErrorCodeSensor(pump, device_id),
        WorkingTimeSensor(pump, device_id),
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


class ModeSensor(DpSensor):
    """working_indicator (DP 125) as an honest label.

    The DP reports the pump's *mode*, not motor activity — ``working`` means
    "in the normal cycle program" even while idle between schedules. The raw
    value stays available as an attribute for automations.
    """

    MODES = {
        "working": "Normal cycle",
        "FP_mode": "FP run",
        "sleep": "Sleep",
        "boost": "Boost",
    }

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [*MODES.values(), "unknown"]

    def __init__(self, coordinator: PumpCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "Mode", DP_STATE, "mdi:pump")

    @property
    def native_value(self) -> str | None:
        raw = (self.coordinator.data or {}).get(self._dp)
        if raw is None:
            return None
        return self.MODES.get(raw, "unknown")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"raw": (self.coordinator.data or {}).get(self._dp)}


class ErrorCodeSensor(DpSensor):
    """Decoded error_code bitmap (DP 114): ``none`` or e.g. ``E93``.

    Keeps the original DP 114 unique_id, so installs that knew this DP as
    "Timer or remaining" retain their entity (the label was wrong — the
    thing model says it's the error bitmap).
    """

    def __init__(self, coordinator: PumpCoordinator, device_id: str) -> None:
        super().__init__(
            coordinator, device_id, "Error code", DP_ERROR_BITMAP, "mdi:alert-decagram-outline"
        )

    @property
    def native_value(self) -> str | None:
        raw = (self.coordinator.data or {}).get(self._dp)
        if raw is None:
            return None
        codes = decode_error_bits(int(raw))
        return ", ".join(codes) if codes else "none"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        raw = (self.coordinator.data or {}).get(self._dp)
        return {"bitmap": raw, "active_errors": decode_error_bits(int(raw or 0))}


class WorkingTimeSensor(DpSensor):
    """working_time (DP 110): runtime counter in hours (0-250)."""

    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PumpCoordinator, device_id: str) -> None:
        super().__init__(
            coordinator, device_id, "Working time", DP_WORKING_TIME, "mdi:timer-sync-outline"
        )


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
