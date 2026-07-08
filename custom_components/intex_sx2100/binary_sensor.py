"""Binary sensors: problem (alarm/error) and mesh connectivity diagnostic."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntexConfigEntry
from .const import (
    CONF_DEVICE_ID,
    DP_ALARM,
    DP_ERROR_BITMAP,
    DP_MESH,
    decode_error_bits,
)
from .coordinator import PumpCoordinator
from .entity import device_info

# Full warntype_indicator enum per the pump's thing model.
KNOWN_ALARMS = {
    "normal": "no alarm",
    "E93": "standby / power-saving (normal — idle between scheduled runs)",
    "DIRTY": "filter dirty — clean or backwash the sand filter",
    "unnormal": "device reports a fault",
}

# Warntype values that are NOT faults — the pump reports these while healthy.
# E93 is Intex's standby / power-saving state, not an error.
NON_FAULT_ALARMS = frozenset({"normal", "E93"})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    device_id = entry.data[CONF_DEVICE_ID]
    pump = entry.runtime_data.pump
    async_add_entities([ProblemSensor(pump, device_id), MeshSensor(pump, device_id)])


class ProblemSensor(CoordinatorEntity[PumpCoordinator], BinarySensorEntity):
    """On when the alarm enum isn't ``normal`` or any error bit is set."""

    _attr_has_entity_name = True
    _attr_name = "Problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: PumpCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{device_id}_problem"
        self._attr_device_info = device_info(device_id)

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data or {}
        alarm = data.get(DP_ALARM)
        bitmap = data.get(DP_ERROR_BITMAP)
        if alarm is None and bitmap is None:
            return None
        alarm_fault = alarm is not None and alarm not in NON_FAULT_ALARMS
        return alarm_fault or bool(bitmap)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        alarm = data.get(DP_ALARM)
        return {
            "code": alarm,
            "description": KNOWN_ALARMS.get(alarm, "unknown code"),
            "active_errors": decode_error_bits(int(data.get(DP_ERROR_BITMAP) or 0)),
        }


class MeshSensor(CoordinatorEntity[PumpCoordinator], BinarySensorEntity):
    """mesh_indicator (DP 119) — diagnostic, disabled by default."""

    _attr_has_entity_name = True
    _attr_name = "Mesh indicator"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PumpCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{device_id}_mesh"
        self._attr_device_info = device_info(device_id)

    @property
    def is_on(self) -> bool | None:
        value = (self.coordinator.data or {}).get(DP_MESH)
        return None if value is None else bool(value)
