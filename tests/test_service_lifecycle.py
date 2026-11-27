"""Isolated action lifecycle regression tests without a Home Assistant install.

Execute the integration's actual functions with fake HA services/coordinators;
imports and unrelated platform dependencies are excluded from this harness.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


SOURCE = Path(__file__).resolve().parents[1] / "custom_components/intex_sx2100/__init__.py"


class HomeAssistantError(Exception):
    """Fake HA action error."""


class ServiceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        names = {
            "async_setup", "async_setup_entry", "async_unload_entry",
            "_async_update_listener", "_schedule_coordinator", "_register_services",
        }
        tree = ast.parse(SOURCE.read_text())
        tree.body = [
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *[node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names],
        ]
        self.namespace = {
            "DOMAIN": "intex_sx2100",
            "SERVICE_SET_SCHEDULE_SLOT": "set_schedule_slot",
            "SERVICE_CLEAR_SCHEDULE_SLOT": "clear_schedule_slot",
            "SET_SLOT_SCHEMA": object(), "CLEAR_SLOT_SCHEMA": object(),
            "HomeAssistantError": HomeAssistantError,
            "CONF_DEVICE_ID": "device_id", "CONF_HOST": "host",
            "CONF_LOCAL_KEY": "local_key", "OPT_LOCAL_INTERVAL": "interval",
            "DEFAULT_LOCAL_INTERVAL": 30, "PLATFORMS": [],
            "CONF_CLOUD_CLIENT_ID": "cloud_id", "CONF_CLOUD_CLIENT_SECRET": "cloud_secret",
            "CONF_CLOUD_REGION": "cloud_region", "DEFAULT_CLOUD_REGION": "eu",
            "OPT_CLOUD_INTERVAL": "cloud_interval", "DEFAULT_CLOUD_INTERVAL": 900,
            "IntexRuntimeData": SimpleNamespace,
            "LocalPump": Mock(),
            "CloudClient": Mock(),
            "ScheduleCoordinator": Mock(),
        }
        exec(compile(ast.fix_missing_locations(tree), str(SOURCE), "exec"), self.namespace)
        self.handlers = {}
        self.hass = SimpleNamespace(
            services=SimpleNamespace(
                has_service=lambda domain, name: name in self.handlers,
                async_register=lambda domain, name, handler, **kwargs: self.handlers.update({name: handler}),
            ),
            config_entries=SimpleNamespace(
                async_loaded_entries=Mock(return_value=[]),
                async_unload_platforms=AsyncMock(return_value=True),
                async_forward_entry_setups=AsyncMock(),
            ),
        )
        self.pump = SimpleNamespace(async_config_entry_first_refresh=AsyncMock())
        self.namespace["PumpCoordinator"] = Mock(return_value=self.pump)

    def make_entry(self, **cloud_settings):
        return SimpleNamespace(
            data={"device_id": "pump", "host": "offline", "local_key": "key", **cloud_settings},
            options={},
            add_update_listener=Mock(),
            async_on_unload=Mock(),
            async_create_background_task=Mock(),
        )

    async def test_actions_survive_failed_first_refresh_and_unload(self):
        self.assertTrue(await self.namespace["async_setup"](self.hass, {}))
        self.assertEqual(set(self.handlers), {"set_schedule_slot", "clear_schedule_slot"})
        original_handlers = self.handlers.copy()
        self.pump.async_config_entry_first_refresh.side_effect = HomeAssistantError("offline")
        entry = self.make_entry(cloud_id="id", cloud_secret="secret")
        with self.assertRaisesRegex(HomeAssistantError, "offline"):
            await self.namespace["async_setup_entry"](self.hass, entry)
        self.namespace["CloudClient"].assert_not_called()
        self.hass.config_entries.async_forward_entry_setups.assert_not_awaited()
        entry.async_create_background_task.assert_not_called()
        for handler in self.handlers.values():
            with self.assertRaisesRegex(HomeAssistantError, "pump unavailable"):
                await handler(SimpleNamespace(data={"slot": 1}))
        self.assertTrue(await self.namespace["async_unload_entry"](self.hass, entry))
        await self.namespace["async_setup"](self.hass, {})
        self.assertEqual(self.handlers, original_handlers)

    async def test_platforms_and_setup_finish_while_first_cloud_read_is_pending(self):
        fetching = asyncio.Event()
        finish = asyncio.Event()

        async def read_schedules():
            fetching.set()
            await finish.wait()

        schedules = SimpleNamespace(async_initial_refresh=read_schedules)
        self.namespace["ScheduleCoordinator"].return_value = schedules
        entry = self.make_entry(cloud_id="id", cloud_secret="secret", cloud_region="us")
        entry.options["cloud_interval"] = 120
        tasks = []

        def start_background(hass, refresh, name):
            self.hass.config_entries.async_forward_entry_setups.assert_awaited_once()
            task = asyncio.create_task(refresh, name=name)
            tasks.append(task)
            return task

        entry.async_create_background_task.side_effect = start_background
        try:
            self.assertTrue(await self.namespace["async_setup_entry"](self.hass, entry))
            await asyncio.wait_for(fetching.wait(), timeout=1)
            self.assertFalse(tasks[0].done())
            self.assertIs(entry.runtime_data.pump, self.pump)
            self.assertIs(entry.runtime_data.schedules, schedules)
            self.namespace["CloudClient"].assert_called_once_with("us", "id", "secret")
            self.namespace["ScheduleCoordinator"].assert_called_once_with(
                self.hass, entry, self.namespace["CloudClient"].return_value, "pump", 120
            )
        finally:
            for task in tasks:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_local_only_and_partial_credentials_skip_cloud_work(self):
        for settings in ({}, {"cloud_id": "id"}, {"cloud_secret": "secret"}):
            with self.subTest(settings=settings):
                entry = self.make_entry(**settings)
                self.assertTrue(await self.namespace["async_setup_entry"](self.hass, entry))
                self.assertIsNone(entry.runtime_data.schedules)
                entry.async_create_background_task.assert_not_called()
        self.namespace["CloudClient"].assert_not_called()

    async def test_failed_platform_setup_does_not_start_cloud_task(self):
        entry = self.make_entry(cloud_id="id", cloud_secret="secret")
        self.hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError("platform")
        with self.assertRaisesRegex(RuntimeError, "platform"):
            await self.namespace["async_setup_entry"](self.hass, entry)
        entry.async_create_background_task.assert_not_called()

    async def test_loaded_entry_without_cloud_reports_credentials(self):
        await self.namespace["async_setup"](self.hass, {})
        self.hass.config_entries.async_loaded_entries.return_value = [
            SimpleNamespace(runtime_data=SimpleNamespace(schedules=None)),
        ]
        with self.assertRaisesRegex(HomeAssistantError, "cloud credentials"):
            await self.handlers["clear_schedule_slot"](SimpleNamespace(data={"slot": 1}))

    async def test_actions_use_current_loaded_coordinator(self):
        await self.namespace["async_setup"](self.hass, {})
        coordinator = SimpleNamespace(async_update_slot=AsyncMock())
        self.hass.config_entries.async_loaded_entries.return_value = [
            SimpleNamespace(runtime_data=SimpleNamespace(schedules=coordinator)),
        ]
        await self.handlers["clear_schedule_slot"](SimpleNamespace(data={"slot": 3}))
        coordinator.async_update_slot.assert_awaited_once_with(2, clear=True)
        await self.handlers["set_schedule_slot"](SimpleNamespace(data={"slot": 7, "hour": 12}))
        coordinator.async_update_slot.assert_awaited_with(
            6, enabled=None, hour=12, minute=None, duration=None, days=None,
        )
        self.hass.config_entries.async_loaded_entries.return_value = []
        with self.assertRaisesRegex(HomeAssistantError, "pump unavailable"):
            await self.handlers["clear_schedule_slot"](SimpleNamespace(data={"slot": 3}))


if __name__ == "__main__":
    unittest.main()
