"""Data coordinators: local pump polling and cloud schedule polling."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import schedule
from .const import DP_PUMP, SCHEDULE_CODE
from .tuya import CloudClient, LocalPump, TuyaError

_LOGGER = logging.getLogger(__name__)
LOCAL_STARTUP_TIMEOUT = 5
CLOUD_REQUEST_TIMEOUT = 10


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
        startup = self.data is None
        try:
            if startup:
                async with asyncio.timeout(LOCAL_STARTUP_TIMEOUT):
                    return await self.hass.async_add_executor_job(
                        partial(self.pump.status, startup=True)
                    )
            return await self.hass.async_add_executor_job(self.pump.status)
        except TimeoutError as err:
            raise UpdateFailed("Timed out reading the pump's local status") from err
        except TuyaError as err:
            # TinyTuya can report a dropped 3.5 handshake as a key error.
            # Keep polling even after a successful connection was lost.
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
        self.last_update_success = False
        self._cloud_io_lock = asyncio.Lock()
        self._cloud_job: asyncio.Future[Any] | None = None
        self._write_lock = asyncio.Lock()
        # Target duration for the "Start FP" button, set by the FP hours
        # number entity (restored across restarts there).
        self.fp_hours: int = 24

    async def async_initial_refresh(self) -> None:
        """Fetch cloud schedules after local entity setup, with normal polling."""
        await self.async_refresh()
        if not self.last_update_success:
            _LOGGER.warning("Tuya Cloud schedules unavailable: %s", self.last_exception)

    async def async_cloud_job(self, operation: Callable[..., Any], *args: Any) -> Any:
        """Serialize SDK calls and cap the async wait for its blocking HTTP I/O."""
        async with self._cloud_io_lock:
            if self._cloud_job is not None and not self._cloud_job.done():
                raise TuyaError("A previous Tuya Cloud request is still running")
            job = self._cloud_job = self.hass.async_add_executor_job(operation, *args)
            # The SDK has no request timeout. Keep at most one worker active per
            # coordinator and collect its exception even if this waiter goes away.
            job.add_done_callback(self._consume_cloud_exception)
            done, _ = await asyncio.wait((job,), timeout=CLOUD_REQUEST_TIMEOUT)
            if not done:
                raise TuyaError("Tuya Cloud request timed out and may still complete")
            return job.result()

    @staticmethod
    def _consume_cloud_exception(job: asyncio.Future[Any]) -> None:
        if not job.cancelled():
            job.exception()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            raw = await self.async_cloud_job(
                self.cloud.get_property, self.device_id, SCHEDULE_CODE
            )
        except TuyaError as err:
            # Rejected optional credentials must not put the local entry into
            # reauth or stop the schedule coordinator from retrying.
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
            raw = await self.async_cloud_job(
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
            await self.async_cloud_job(
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

    # The native app reserves slot 1 as the dedicated "FP Mode" slot.
    FP_SLOT_INDEX = 0

    async def async_start_fp(self) -> None:
        """Start an FP run in slot 1 — the same slot the native app uses for
        FP mode. A dated one-time entry (days == 0), enabled, up to 48 h; the
        pump runs it once and returns to the normal cycle. Real schedules live
        in the other slots and are never touched."""
        async with self._write_lock:
            slots = await self._fresh_slots()
            start = dt_util.now() + timedelta(minutes=1)
            new = schedule.set_slot(
                slots,
                self.FP_SLOT_INDEX,
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
