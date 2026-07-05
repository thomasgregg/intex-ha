"""Start-FP button: one-time long filtration run, then back to normal cycle."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntexConfigEntry
from .const import CONF_DEVICE_ID
from .coordinator import ScheduleCoordinator
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the FP button (cloud schedules only)."""
    coordinator = entry.runtime_data.schedules
    if coordinator is None:
        return
    async_add_entities([StartFpButton(coordinator, entry.data[CONF_DEVICE_ID])])


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
