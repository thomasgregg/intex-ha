"""Problem sensor: on whenever the pump reports an alarm code (DP 127)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntexConfigEntry
from .const import CONF_DEVICE_ID, DP_ALARM
from .coordinator import PumpCoordinator
from .entity import device_info

# Meanings observed on real pumps; extended as codes are reported.
KNOWN_ALARMS = {
    "E93": "E93 (observed on this pump; exact meaning unverified)",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the problem sensor."""
    async_add_entities(
        [ProblemSensor(entry.runtime_data.pump, entry.data[CONF_DEVICE_ID])]
    )


class ProblemSensor(CoordinatorEntity[PumpCoordinator], BinarySensorEntity):
    """On when DP 127 reports anything other than ``normal``."""

    _attr_has_entity_name = True
    _attr_name = "Problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: PumpCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{device_id}_problem"
        self._attr_device_info = device_info(device_id)

    @property
    def is_on(self) -> bool | None:
        alarm = (self.coordinator.data or {}).get(DP_ALARM)
        return None if alarm is None else alarm != "normal"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alarm = (self.coordinator.data or {}).get(DP_ALARM)
        return {
            "code": alarm,
            "description": KNOWN_ALARMS.get(alarm, "no alarm" if alarm == "normal" else "unknown code"),
        }
