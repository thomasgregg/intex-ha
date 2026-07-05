"""Data coordinators: local pump polling and cloud schedule polling."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import schedule
from .const import DP_PUMP, SCHEDULE_CODE
from .tuya import CloudClient, LocalPump, TuyaAuthError, TuyaError

_LOGGER = logging.getLogger(__name__)


class PumpCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the pump's local DP status."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        pump: LocalPump,
        interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Intex SX2100 pump",
            config_entry=entry,
            update_interval=timedelta(seconds=interval),
        )
        self.pump = pump

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.hass.async_add_executor_job(self.pump.status)
        except TuyaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TuyaError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001 — tinytuya raises broadly
            raise UpdateFailed(f"{type(err).__name__}: {err}") from err

    async def async_set_pump(self, on: bool) -> None:
        """Switch the pump, publish optimistically, then confirm by refresh."""
        await self.hass.async_add_executor_job(self.pump.set_pump, DP_PUMP, on)
        if self.data is not None:
            self.async_set_updated_data({**self.data, DP_PUMP: on})
        await self.async_request_refresh()


class ScheduleCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Read/write the cloud-only skdl_filter schedule blob."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        cloud: CloudClient,
        device_id: str,
        interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Intex SX2100 schedule",
            config_entry=entry,
            update_interval=timedelta(seconds=interval),
        )
        self.cloud = cloud
        self.device_id = device_id
        self._write_lock = asyncio.Lock()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            raw = await self.hass.async_add_executor_job(
                self.cloud.get_property, self.device_id, SCHEDULE_CODE
            )
        except TuyaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TuyaError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"{type(err).__name__}: {err}") from err
        return {"raw": raw, "slots": schedule.decode_schedules(raw)}

    async def async_update_slot(
        self,
        index: int,
        *,
        enabled: bool | None = None,
        hour: int | None = None,
        minute: int | None = None,
        duration: int | None = None,
        days: int | None = None,
        clear: bool = False,
    ) -> None:
        """Update one slot with sensible defaults for previously-empty slots."""
        slots = (self.data or {}).get("slots") or schedule.decode_schedules(None)
        was_empty = not (0 <= index < len(slots) and slots[index].get("active"))
        new = schedule.set_slot(
            slots,
            index,
            enabled=enabled,
            hour=hour,
            minute=minute,
            duration=duration,
            days=days,
            clear=clear,
        )
        rec = new[index]
        if not clear and was_empty and rec.get("active"):
            # A truly empty slot being brought to life needs a repeat mask and
            # a non-zero worktime, or the pump ignores it. Existing entries are
            # never touched: FP-mode slots legitimately have days == 0, and
            # forcing a mask on them would turn a one-time run into a daily one.
            if days is None and not rec.get("days"):
                rec["days"] = schedule.DAYS_EVERY
            if not rec.get("duration"):
                rec["duration"] = 1
        await self.async_write_slots(new)

    async def async_write_slots(self, slots: list[dict[str, Any]]) -> None:
        """Write slots back. Serialized + optimistic: the cloud takes a few
        seconds to reflect a write, and a second edit inside that window would
        otherwise read the stale blob and undo the first edit."""
        async with self._write_lock:
            b64 = schedule.encode_schedules(slots)
            await self.hass.async_add_executor_job(
                self.cloud.set_property, self.device_id, SCHEDULE_CODE, b64
            )
            self.async_set_updated_data(
                {"raw": b64, "slots": schedule.decode_schedules(b64)}
            )
            await asyncio.sleep(5)
        await self.async_request_refresh()
