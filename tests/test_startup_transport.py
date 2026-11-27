"""Startup transport tests with no network or Home Assistant installation."""
from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class HomeAssistantError(Exception):
    pass


class ConfigEntryAuthFailed(HomeAssistantError):
    pass


class UpdateFailed(HomeAssistantError):
    pass


class DataUpdateCoordinator:
    @classmethod
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, *, name, config_entry, update_interval):
        self.hass = hass
        self.data = None
        self.last_update_success = True
        self.last_exception = None

    async def async_refresh(self):
        try:
            self.data = await self._async_update_data()
        except UpdateFailed as err:
            self.last_update_success = False
            self.last_exception = err
        else:
            self.last_update_success = True


def load_components():
    """Import the real modules with only their external dependencies stubbed."""
    package = ModuleType("intex_startup_tests")
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/intex_sx2100")]
    external = {
        package.__name__: package,
        "homeassistant": ModuleType("homeassistant"),
        "homeassistant.config_entries": SimpleNamespace(ConfigEntry=object),
        "homeassistant.core": SimpleNamespace(HomeAssistant=object),
        "homeassistant.exceptions": SimpleNamespace(
            ConfigEntryAuthFailed=ConfigEntryAuthFailed, HomeAssistantError=HomeAssistantError
        ),
        "homeassistant.helpers": ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.update_coordinator": SimpleNamespace(
            DataUpdateCoordinator=DataUpdateCoordinator, UpdateFailed=UpdateFailed
        ),
        "homeassistant.util": SimpleNamespace(dt=SimpleNamespace()),
        "tinytuya": SimpleNamespace(Device=Mock(), Cloud=Mock()),
    }
    with patch.dict(sys.modules, external):
        coordinator = importlib.import_module(f"{package.__name__}.coordinator")
        return coordinator, importlib.import_module(f"{package.__name__}.tuya")


coordinator, tuya = load_components()


def completed_executor_job(operation, *args):
    job = asyncio.get_running_loop().create_future()
    try:
        job.set_result(operation(*args))
    except Exception as err:
        job.set_exception(err)
    return job


class LocalStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_poll_is_bounded_and_later_polls_use_normal_status(self):
        pump = Mock()
        pump.status.return_value = {"104": False}
        hass = SimpleNamespace(async_add_executor_job=completed_executor_job)
        local = coordinator.PumpCoordinator(hass, object(), pump, 15)
        local.data = await local._async_update_data()
        self.assertEqual(local.data, {"104": False})
        pump.status.assert_called_once_with(startup=True)
        await local._async_update_data()
        pump.status.assert_called_with()

    async def test_stalled_executor_does_not_extend_local_startup_budget(self):
        pending = asyncio.get_running_loop().create_future()
        hass = SimpleNamespace(async_add_executor_job=Mock(return_value=pending))
        local = coordinator.PumpCoordinator(hass, object(), Mock(), 15)
        with patch.object(coordinator, "LOCAL_STARTUP_TIMEOUT", 0):
            with self.assertRaisesRegex(UpdateFailed, "Timed out reading the pump"):
                await local._async_update_data()
        self.assertTrue(pending.cancelled())
        self.assertIsNone(local.data)

    async def test_offline_and_ambiguous_handshake_are_retryable_at_startup(self):
        pump = Mock()
        hass = SimpleNamespace(async_add_executor_job=completed_executor_job)
        local = coordinator.PumpCoordinator(hass, object(), pump, 15)
        for err in (tuya.TuyaError("Err=901"), tuya.TuyaAuthError("Err=914")):
            with self.subTest(error=err):
                pump.status.side_effect = err
                with self.assertRaisesRegex(UpdateFailed, str(err)):
                    await local._async_update_data()

    async def test_online_pump_stays_unavailable_across_repeated_offline_polls(self):
        pump = Mock()
        pump.status.side_effect = [
            {"104": True},
            tuya.TuyaError("Err=901"),
            tuya.TuyaError("Err=905"),
            tuya.TuyaError("Err=901"),
        ]
        hass = SimpleNamespace(async_add_executor_job=completed_executor_job)
        local = coordinator.PumpCoordinator(hass, object(), pump, 15)

        await local.async_refresh()
        self.assertTrue(local.last_update_success)
        for code in ("901", "905", "901"):
            await local.async_refresh()
            self.assertFalse(local.last_update_success)
            self.assertIn(code, str(local.last_exception))
        self.assertEqual(pump.status.call_count, 4)

    async def test_online_pump_recovers_from_handshake_error_and_connection_loss(self):
        pump = Mock()
        pump.status.side_effect = [
            {"104": True},
            tuya.TuyaAuthError("Err=914"),
            tuya.TuyaError("Err=901"),
            {"104": False},
        ]
        hass = SimpleNamespace(async_add_executor_job=completed_executor_job)
        local = coordinator.PumpCoordinator(hass, object(), pump, 15)

        await local.async_refresh()
        self.assertTrue(local.last_update_success)
        for code in ("914", "901"):
            await local.async_refresh()
            self.assertFalse(local.last_update_success)
            self.assertIsInstance(local.last_exception, UpdateFailed)
            self.assertIn(code, str(local.last_exception))
        await local.async_refresh()
        self.assertTrue(local.last_update_success)
        self.assertEqual(local.data, {"104": False})

    def test_socket_retry_overrides_apply_only_to_startup_status(self):
        startup_device, poll_device, write_device = (Mock() for _ in range(3))
        for dev in (startup_device, poll_device):
            dev.status.return_value = {"dps": {"104": False}}
        write_device.set_value.return_value = {}
        pump = tuya.LocalPump("device", "192.0.2.1", "key")
        with patch.object(tuya.tinytuya, "Device", side_effect=[startup_device, poll_device, write_device]):
            self.assertEqual(pump.status(startup=True), {"104": False})
            self.assertEqual(pump.status(), {"104": False})
            pump.set_pump("104", True)
        startup_device.set_socketTimeout.assert_called_once_with(3)
        startup_device.set_socketRetryLimit.assert_called_once_with(1)
        startup_device.set_socketRetryDelay.assert_called_once_with(0)
        for dev in (poll_device, write_device):
            dev.set_socketTimeout.assert_called_once_with(5)
            dev.set_socketRetryLimit.assert_not_called()
            dev.set_socketRetryDelay.assert_not_called()
        for dev in (startup_device, poll_device, write_device):
            dev.set_version.assert_called_once_with(3.5)
            dev.set_socketPersistent.assert_called_once_with(False)
        write_device.set_value.assert_called_once_with(104, True)


class CloudStartupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.executor = Mock(side_effect=completed_executor_job)
        self.hass = SimpleNamespace(async_add_executor_job=self.executor)
        self.cloud = Mock()
        self.schedules = coordinator.ScheduleCoordinator(self.hass, object(), self.cloud, "device", 900)

    async def test_cloud_auth_failure_recovers_without_entry_reauth(self):
        self.assertFalse(self.schedules.last_update_success)
        self.assertIsNone(self.schedules.data)
        self.cloud.get_property.side_effect = [tuya.TuyaAuthError("rejected"), None]
        with self.assertLogs(coordinator.__name__, "WARNING") as logs:
            await self.schedules.async_initial_refresh()
        self.assertIn("rejected", logs.output[0])
        self.assertIsInstance(self.schedules.last_exception, UpdateFailed)
        self.assertFalse(self.schedules.last_update_success)
        self.assertIsNone(self.schedules.data)
        await self.schedules.async_refresh()
        self.assertTrue(self.schedules.last_update_success)
        self.assertEqual(len(self.schedules.data["slots"]), 7)

    async def test_cloud_timeout_consumes_late_failure_and_does_not_spawn_more_workers(self):
        pending = asyncio.get_running_loop().create_future()
        self.cloud.get_property.return_value = None
        self.executor.side_effect = None
        self.executor.return_value = pending
        with patch.object(coordinator, "CLOUD_REQUEST_TIMEOUT", 0):
            with self.assertRaisesRegex(UpdateFailed, "timed out"):
                await self.schedules._async_update_data()
        self.assertFalse(pending.cancelled())
        with self.assertRaisesRegex(UpdateFailed, "still running"):
            await self.schedules._async_update_data()
        with self.assertRaisesRegex(HomeAssistantError, "still running"):
            await self.schedules.async_update_slot(0, clear=True)
        self.executor.assert_called_once()
        pending.set_exception(tuya.TuyaError("late read failure"))
        self.executor.side_effect = completed_executor_job
        await self.schedules.async_refresh()
        self.assertTrue(self.schedules.last_update_success)
        self.assertEqual(self.executor.call_count, 2)
        self.cloud.set_property.assert_not_called()

    async def test_cloud_reads_queue_behind_an_active_sdk_call(self):
        first_job = asyncio.get_running_loop().create_future()
        started = asyncio.Event()

        def launch(operation, *args):
            if operation == self.cloud.get_model:
                started.set()
                return first_job
            return completed_executor_job(operation, *args)

        self.executor.side_effect = launch
        self.cloud.get_property.return_value = None
        diagnostics = asyncio.create_task(
            self.schedules.async_cloud_job(self.cloud.get_model, "device")
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        refresh = asyncio.create_task(self.schedules.async_refresh())
        await asyncio.sleep(0)
        self.executor.assert_called_once()
        first_job.set_result({"model": "test"})
        self.assertEqual(await diagnostics, {"model": "test"})
        await refresh
        self.assertTrue(self.schedules.last_update_success)
        self.assertEqual(self.executor.call_count, 2)

    async def test_cancelling_initial_refresh_prevents_late_state_publication(self):
        started = asyncio.Event()
        pending = asyncio.get_running_loop().create_future()

        def stalled_read(operation, *args):
            started.set()
            return pending

        self.executor.side_effect = stalled_read
        refresh = asyncio.create_task(self.schedules.async_initial_refresh())
        await asyncio.wait_for(started.wait(), timeout=1)
        refresh.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await refresh
        pending.set_result(None)
        await asyncio.sleep(0)
        self.assertFalse(self.schedules.last_update_success)
        self.assertIsNone(self.schedules.data)

    async def test_failed_fresh_read_never_writes_a_schedule(self):
        self.cloud.get_property.side_effect = tuya.TuyaError("offline")
        with self.assertRaisesRegex(HomeAssistantError, "Could not read the current schedule"):
            await self.schedules.async_update_slot(0, enabled=True)
        self.cloud.set_property.assert_not_called()

    async def test_timed_out_write_does_not_publish_or_retry_the_write(self):
        pending = asyncio.get_running_loop().create_future()

        def launch(operation, *args):
            if operation == self.cloud.set_property:
                return pending
            return completed_executor_job(operation, *args)

        self.executor.side_effect = launch
        self.cloud.get_property.return_value = None
        with patch.object(coordinator, "CLOUD_REQUEST_TIMEOUT", 0):
            with self.assertRaisesRegex(HomeAssistantError, "may still complete"):
                await self.schedules.async_update_slot(0, enabled=True)
        with self.assertRaisesRegex(HomeAssistantError, "still running"):
            await self.schedules.async_update_slot(0, enabled=True)
        self.assertEqual(self.executor.call_count, 2)
        pending.set_result(None)
        await asyncio.sleep(0)
        self.assertIsNone(self.schedules.data)

    def test_client_authenticates_lazily_and_reuses_then_replaces_rejected_token(self):
        first = Mock(token="first")
        second = Mock(token="second")
        reply = {"success": True, "result": {"properties": [{"code": "skdl_filter", "value": "blob"}]}}
        first.cloudrequest.side_effect = [reply, reply, {"success": False, "code": 1010}]
        second.cloudrequest.return_value = reply
        with patch.object(tuya.tinytuya, "Cloud", side_effect=[first, second]) as factory:
            client = tuya.CloudClient("eu", "id", "secret")
            factory.assert_not_called()
            self.assertEqual(client.get_property("device", "skdl_filter"), "blob")
            self.assertEqual(client.get_property("device", "skdl_filter"), "blob")
            factory.assert_called_once_with(apiRegion="eu", apiKey="id", apiSecret="secret")
            with self.assertRaises(tuya.TuyaAuthError):
                client.get_property("device", "skdl_filter")
            self.assertEqual(client.get_property("device", "skdl_filter"), "blob")
            self.assertEqual(factory.call_count, 2)

    def test_transient_token_request_failure_can_be_retried(self):
        connected = Mock(token="token")
        with patch.object(tuya.tinytuya, "Cloud", side_effect=[OSError("offline"), connected]) as factory:
            client = tuya.CloudClient("eu", "id", "secret")
            with self.assertRaisesRegex(tuya.TuyaError, "token request failed"):
                client.connect()
            client.connect()
            client.connect()
            self.assertEqual(factory.call_count, 2)


if __name__ == "__main__":
    unittest.main()
