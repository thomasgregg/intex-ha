"""Diagnostics: local DPs, schedule state, and the Tuya thing model.

The thing model names every DP officially (types, enum values), so a
diagnostics download is the reference for identifying unknown DPs
(106/110/119) and the full alarm code list.
"""
from __future__ import annotations

import json
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import IntexConfigEntry
from .const import CONF_CLOUD_CLIENT_ID, CONF_CLOUD_CLIENT_SECRET, CONF_DEVICE_ID, CONF_LOCAL_KEY

TO_REDACT = {CONF_LOCAL_KEY, CONF_CLOUD_CLIENT_ID, CONF_CLOUD_CLIENT_SECRET}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IntexConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    data = entry.runtime_data
    diag: dict[str, Any] = {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "local_dps": data.pump.data,
        "schedule": data.schedules.data if data.schedules else None,
    }
    if data.schedules is not None:
        device_id = entry.data[CONF_DEVICE_ID]
        cloud = data.schedules.cloud
        for key, call in (
            ("cloud_properties", cloud.get_all_properties),
            ("thing_model", cloud.get_model),
        ):
            try:
                result = await hass.async_add_executor_job(call, device_id)
            except Exception as err:  # noqa: BLE001 — diagnostics must not fail
                diag[key] = f"unavailable: {type(err).__name__}: {err}"
                continue
            # The model's "model" field is itself a JSON string — unpack it
            # so the download is readable.
            if key == "thing_model" and isinstance(result, dict) and isinstance(
                result.get("model"), str
            ):
                try:
                    result = {**result, "model": json.loads(result["model"])}
                except ValueError:
                    pass
            diag[key] = result
    return diag
