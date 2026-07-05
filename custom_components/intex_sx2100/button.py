"""Buttons: Start FP (one-time long run) and Refresh (force re-poll)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntexConfigEntry
from .const import CONF_DEVICE_ID
from .coordinator import PumpCoordinator, ScheduleCoordinator
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the buttons."""
    device_id = entry.data[CONF_DEVICE_ID]
    entities: list[Entity] = [
        RefreshButton(entry.runtime_data.pump, entry.runtime_data.schedules, device_id)
    ]
    if (schedules := entry.runtime_data.schedules) is not None:
        entities.append(StartFpButton(schedules, device_id))
    async_add_entities(entities)


class RefreshButton(ButtonEntity):
    """Force an immediate re-poll of the pump and, if present, the cloud."""

    _attr_has_entity_name = True
    _attr_name = "Refresh"
    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        pump: PumpCoordinator,
        schedules: ScheduleCoordinator | None,
        device_id: str,
    ) -> None:
        self._pump = pump
        self._schedules = schedules
        self._attr_unique_id = f"{device_id}_refresh"
        self._attr_device_info = device_info(device_id)

    async def async_press(self) -> None:
        await self._pump.async_refresh()
        if self._schedules is not None:
            await self._schedules.async_refresh()


class StartFpButton(CoordinatorEntity[ScheduleCoordinator], ButtonEntity):
    """Press to start an FP run of "FP hours" duration in ~2 minutes."""

    _attr_has_entity_name = True
    _attr_name = "Start FP"
    _attr_icon = "mdi:rocket-launch"

    def __init__(self, coordinator: ScheduleCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{device_id}_start_fp"
        self._attr_device_info = device_info(device_id)

    async def async_press(self) -> None:
        await self.coordinator.async_start_fp()
