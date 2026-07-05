"""Intex SX2100 WiFi sand filter pump (AGP SAND FILTER PUMP R1).

Local control via tinytuya (protocol 3.5), optional Tuya-cloud schedule
support for the pump's internal timer program (skdl_filter).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from . import schedule
from .const import (
    CONF_CLOUD_CLIENT_ID,
    CONF_CLOUD_CLIENT_SECRET,
    CONF_CLOUD_REGION,
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    DEFAULT_CLOUD_INTERVAL,
    DEFAULT_CLOUD_REGION,
    DEFAULT_LOCAL_INTERVAL,
    DOMAIN,
    OPT_CLOUD_INTERVAL,
    OPT_LOCAL_INTERVAL,
    SERVICE_CLEAR_SCHEDULE_SLOT,
    SERVICE_SET_SCHEDULE_SLOT,
)
from .coordinator import PumpCoordinator, ScheduleCoordinator
from .tuya import CloudClient, LocalPump, TuyaError

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]


@dataclass
class IntexRuntimeData:
    """Runtime objects stored on the config entry."""

    pump: PumpCoordinator
    schedules: ScheduleCoordinator | None


IntexConfigEntry = ConfigEntry[IntexRuntimeData]

SET_SLOT_SCHEMA = vol.Schema(
    {
        vol.Required("slot"): vol.All(vol.Coerce(int), vol.Range(min=1, max=7)),
        vol.Optional("enabled"): cv.boolean,
        vol.Optional("hour"): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
        vol.Optional("minute"): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
        vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
        vol.Optional("days"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
    }
)

CLEAR_SLOT_SCHEMA = vol.Schema(
    {vol.Required("slot"): vol.All(vol.Coerce(int), vol.Range(min=1, max=7))}
)


async def async_setup_entry(hass: HomeAssistant, entry: IntexConfigEntry) -> bool:
    """Set up the pump from a config entry."""
    pump = LocalPump(
        entry.data[CONF_DEVICE_ID],
        entry.data[CONF_HOST],
        entry.data[CONF_LOCAL_KEY],
    )
    pump_coordinator = PumpCoordinator(
        hass,
        entry,
        pump,
        entry.options.get(OPT_LOCAL_INTERVAL, DEFAULT_LOCAL_INTERVAL),
    )
    await pump_coordinator.async_config_entry_first_refresh()

    # Cloud schedules are optional: local control must never depend on them.
    schedules: ScheduleCoordinator | None = None
    client_id = entry.data.get(CONF_CLOUD_CLIENT_ID)
    client_secret = entry.data.get(CONF_CLOUD_CLIENT_SECRET)
    if client_id and client_secret:
        try:
            cloud = await hass.async_add_executor_job(
                CloudClient,
                entry.data.get(CONF_CLOUD_REGION, DEFAULT_CLOUD_REGION),
                client_id,
                client_secret,
            )
        except TuyaError as err:
            _LOGGER.warning(
                "Tuya cloud unavailable, schedule entities disabled: %s", err
            )
        else:
            schedules = ScheduleCoordinator(
                hass,
                entry,
                cloud,
                entry.data[CONF_DEVICE_ID],
                entry.options.get(OPT_CLOUD_INTERVAL, DEFAULT_CLOUD_INTERVAL),
            )
            await schedules.async_config_entry_first_refresh()

    entry.runtime_data = IntexRuntimeData(pump=pump_coordinator, schedules=schedules)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IntexConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: IntexConfigEntry) -> None:
    """Reload on options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _schedule_coordinator(hass: HomeAssistant) -> ScheduleCoordinator:
    """Find the schedule coordinator or explain why there is none."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        data: IntexRuntimeData = entry.runtime_data
        if data.schedules is not None:
            return data.schedules
    raise HomeAssistantError(
        "Schedule support requires Tuya cloud credentials — reconfigure the "
        "integration and add a cloud client ID and secret"
    )


def _register_services(hass: HomeAssistant) -> None:
    """Register the schedule services once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE_SLOT):
        return

    async def set_slot(call: ServiceCall) -> None:
        coordinator = _schedule_coordinator(hass)
        slots = (coordinator.data or {}).get("slots") or schedule.decode_schedules(None)
        new = schedule.set_slot(
            slots,
            call.data["slot"] - 1,
            enabled=call.data.get("enabled"),
            hour=call.data.get("hour"),
            minute=call.data.get("minute"),
            duration=call.data.get("duration"),
            days=call.data.get("days"),
        )
        await coordinator.async_write_slots(new)

    async def clear_slot(call: ServiceCall) -> None:
        coordinator = _schedule_coordinator(hass)
        slots = (coordinator.data or {}).get("slots") or schedule.decode_schedules(None)
        new = schedule.set_slot(slots, call.data["slot"] - 1, clear=True)
        await coordinator.async_write_slots(new)

    hass.services.async_register(
        DOMAIN, SERVICE_SET_SCHEDULE_SLOT, set_slot, schema=SET_SLOT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_SCHEDULE_SLOT, clear_slot, schema=CLEAR_SLOT_SCHEMA
    )
