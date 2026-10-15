"""Isolated action lifecycle regression tests without a Home Assistant install.

Execute the integration's actual functions with fake HA services/coordinators;
imports and unrelated platform dependencies are excluded from this harness.
"""
from __future__ import annotations

import ast
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
            "_schedule_coordinator", "_register_services",
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
            ),
        )

    async def test_actions_survive_failed_first_refresh_and_unload(self):
        self.assertTrue(await self.namespace["async_setup"](self.hass, {}))
        self.assertEqual(set(self.handlers), {"set_schedule_slot", "clear_schedule_slot"})
        original_handlers = self.handlers.copy()
        self.namespace["LocalPump"] = Mock()
        self.namespace["PumpCoordinator"] = Mock(return_value=SimpleNamespace(
            async_config_entry_first_refresh=AsyncMock(side_effect=HomeAssistantError("offline")),
        ))
        entry = SimpleNamespace(data={"device_id": "pump", "host": "offline", "local_key": "key"}, options={})
        with self.assertRaisesRegex(HomeAssistantError, "offline"):
            await self.namespace["async_setup_entry"](self.hass, entry)
        for handler in self.handlers.values():
            with self.assertRaisesRegex(HomeAssistantError, "pump unavailable"):
                await handler(SimpleNamespace(data={"slot": 1}))
        self.assertTrue(await self.namespace["async_unload_entry"](self.hass, entry))
        await self.namespace["async_setup"](self.hass, {})
        self.assertEqual(self.handlers, original_handlers)

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
