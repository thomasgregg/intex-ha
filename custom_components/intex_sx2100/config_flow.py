"""Config flow: local connection required, Tuya cloud credentials optional."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback

from .const import (
    CLOUD_REGIONS,
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
)
from .tuya import CloudClient, LocalPump, TuyaAuthError, TuyaError

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_LOCAL_KEY): str,
        vol.Optional(CONF_CLOUD_REGION, default=DEFAULT_CLOUD_REGION): vol.In(
            CLOUD_REGIONS
        ),
        vol.Optional(CONF_CLOUD_CLIENT_ID): str,
        vol.Optional(CONF_CLOUD_CLIENT_SECRET): str,
    }
)


class IntexConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single-step setup with live validation."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()

            # Validate local connection (protocol 3.5).
            pump = LocalPump(
                user_input[CONF_DEVICE_ID],
                user_input[CONF_HOST],
                user_input[CONF_LOCAL_KEY],
            )
            try:
                await self.hass.async_add_executor_job(pump.status)
            except TuyaAuthError:
                errors["base"] = "invalid_auth"
            except (TuyaError, OSError):
                errors["base"] = "cannot_connect"

            # Validate cloud credentials only if both were provided.
            client_id = user_input.get(CONF_CLOUD_CLIENT_ID)
            client_secret = user_input.get(CONF_CLOUD_CLIENT_SECRET)
            if not errors and bool(client_id) != bool(client_secret):
                errors["base"] = "cloud_incomplete"
            if not errors and client_id and client_secret:
                try:
                    await self.hass.async_add_executor_job(
                        CloudClient,
                        user_input.get(CONF_CLOUD_REGION, DEFAULT_CLOUD_REGION),
                        client_id,
                        client_secret,
                    )
                except TuyaAuthError:
                    errors["base"] = "cloud_invalid_auth"
                except TuyaError:
                    errors["base"] = "cloud_cannot_connect"

            if not errors:
                return self.async_create_entry(
                    title="Intex SX2100 Pool Pump", data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> IntexOptionsFlow:
        """Get the options flow."""
        return IntexOptionsFlow()


class IntexOptionsFlow(OptionsFlow):
    """Adjust polling intervals."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        OPT_LOCAL_INTERVAL,
                        default=options.get(OPT_LOCAL_INTERVAL, DEFAULT_LOCAL_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=300)),
                    vol.Required(
                        OPT_CLOUD_INTERVAL,
                        default=options.get(OPT_CLOUD_INTERVAL, DEFAULT_CLOUD_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
                }
            ),
        )
