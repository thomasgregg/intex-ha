"""Pump switch (local DP 104)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntexConfigEntry
from .const import CONF_DEVICE_ID, DP_PUMP
from .coordinator import PumpCoordinator
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the pump switch."""
    async_add_entities(
        [PumpSwitch(entry.runtime_data.pump, entry.data[CONF_DEVICE_ID])]
    )


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
