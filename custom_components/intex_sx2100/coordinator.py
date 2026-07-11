"""Data coordinators: local pump polling and cloud schedule polling."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

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

    async def async_set_bool(self, dp: str, on: bool) -> None:
        """Write a boolean DP, publish optimistically, then confirm by refresh."""
        await self.hass.async_add_executor_job(self.pump.set_pump, dp, on)
        if self.data is not None:
            self.async_set_updated_data({**self.data, dp: on})
        await self.async_request_refresh()

    async def async_set_pump(self, on: bool) -> None:
        """Switch the pump (DP 104)."""
        await self.async_set_bool(DP_PUMP, on)


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
        # Target duration for the "Start FP" button, set by the FP hours
        # number entity (restored across restarts there).
        self.fp_hours: int = 24

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

    async def _fresh_slots(self) -> list[dict[str, Any]]:
        """Read the CURRENT blob from the cloud (never trust the poll cache).

        Every write uploads all 56 bytes, so basing it on a cached blob (up to
        one poll interval old) would resurrect schedules deleted in the app or
        overwrite edits made there. Caller must hold the write lock.
        """
        try:
            raw = await self.hass.async_add_executor_job(
                self.cloud.get_property, self.device_id, SCHEDULE_CODE
            )
        except TuyaError as err:
            raise HomeAssistantError(
                f"Could not read the current schedule before writing: {err}"
            ) from err
        return schedule.decode_schedules(raw)

    async def _write_slots(self, slots: list[dict[str, Any]]) -> None:
        """Upload the blob and publish optimistically. Caller holds the lock;
        the 5 s settle wait keeps a second edit from reading the stale cloud
        state mid-propagation."""
        b64 = schedule.encode_schedules(slots)
        try:
            await self.hass.async_add_executor_job(
                self.cloud.set_property, self.device_id, SCHEDULE_CODE, b64
            )
        except TuyaError as err:
            raise HomeAssistantError(f"Schedule write failed: {err}") from err
        self.async_set_updated_data(
            {"raw": b64, "slots": schedule.decode_schedules(b64)}
        )
        await asyncio.sleep(5)

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
        """Read-modify-write one slot against fresh cloud state."""
        async with self._write_lock:
            slots = await self._fresh_slots()
            was_empty = not slots[index].get("active")
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
                # A truly empty slot being brought to life needs a repeat mask
                # and a non-zero worktime, or the pump ignores it. Existing
                # entries are never touched: FP-mode slots legitimately have
                # days == 0, and forcing a mask would make them daily.
                if days is None and not rec.get("days"):
                    rec["days"] = schedule.DAYS_EVERY
                if not rec.get("duration"):
                    rec["duration"] = 1
            await self._write_slots(new)
        await self.async_request_refresh()

    async def async_start_fp(self) -> None:
        """Write a one-time FP entry into a free slot, starting in ~2 minutes.

        Mirrors the app's FP mode: dated entry, days == 0, enabled, duration
        up to 48 h. The pump runs it once, then returns to the normal cycle.
        """
        async with self._write_lock:
            slots = await self._fresh_slots()
            # Prefer an empty slot; otherwise recycle a finished FP entry
            # (dated one-time run, days == 0, no longer enabled) so repeated
            # FP presses don't fill all 7 slots with stale entries.
            def _free(s: dict[str, Any]) -> bool:
                return not s.get("active")

            def _spent_fp(s: dict[str, Any]) -> bool:
                return not s.get("days") and not s.get("on") and s.get("active")

            index = next(
                (i for i, s in enumerate(slots) if _free(s)),
                next((i for i, s in enumerate(slots) if _spent_fp(s)), None),
            )
            if index is None:
                raise HomeAssistantError(
                    "All 7 schedule slots are in use — clear one first"
                )
            start = dt_util.now() + timedelta(minutes=1)
            new = schedule.set_slot(
                slots,
                index,
                enabled=True,
                month=start.month,
                date=start.day,
                hour=start.hour,
                minute=start.minute,
                duration=max(1, min(int(self.fp_hours), 48)),
                days=0,
            )
            await self._write_slots(new)
        await self.async_request_refresh()
