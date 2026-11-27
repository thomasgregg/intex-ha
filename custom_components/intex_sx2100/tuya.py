"""Thin, blocking tinytuya wrappers. No Home Assistant imports.

Plain synchronous callables so coordinators can run them via
``hass.async_add_executor_job``. A fresh, non-persistent socket is used per
call: persistent sockets on this pump were observed to serve stale DP values
and swallow commands.
"""
from __future__ import annotations

import json
from typing import Any

import tinytuya

from .const import PROTOCOL_VERSION


class TuyaError(Exception):
    """A Tuya local or cloud operation failed."""


class TuyaAuthError(TuyaError):
    """Credentials rejected (bad local key or cloud client id/secret)."""


# tinytuya local error code for "Check device key or version"
_LOCAL_AUTH_ERRS = {"914"}
# Tuya cloud codes for bad sign / token / permission
_CLOUD_AUTH_CODES = {1004, 1010, 1011, 1100, 1106, 2406, 28841002}


class LocalPump:
    """Local LAN access to the SX2100 pump (Tuya protocol 3.5 only)."""

    def __init__(self, device_id: str, host: str, local_key: str) -> None:
        self._device_id = device_id
        self._host = host
        self._local_key = local_key

    def _device(self, *, startup: bool = False) -> Any:
        dev = tinytuya.Device(self._device_id, self._host, self._local_key)
        dev.set_version(PROTOCOL_VERSION)
        dev.set_socketPersistent(False)
        dev.set_socketTimeout(3 if startup else 5)
        if startup:
            dev.set_socketRetryLimit(1)
            dev.set_socketRetryDelay(0)
        return dev

    def status(self, *, startup: bool = False) -> dict[str, Any]:
        """Return the DP dict, e.g. {"104": False, "125": "working", ...}."""
        data = self._device(startup=startup).status()
        if isinstance(data, dict) and isinstance(data.get("dps"), dict):
            return data["dps"]
        self._raise("status", data)

    def set_pump(self, dp: str, on: bool) -> None:
        """Set the pump DP. tinytuya returns an error dict instead of raising."""
        resp = self._device().set_value(int(dp), bool(on))
        if isinstance(resp, dict) and resp.get("Err"):
            self._raise(f"set dp {dp}", resp)

    def _raise(self, what: str, data: Any) -> None:
        if isinstance(data, dict):
            err = str(data.get("Err") or "")
            msg = f"{what} failed: Err={err or '?'} ({str(data.get('Error'))[:80]})"
        else:
            err = ""
            msg = f"{what} failed: unexpected response ({type(data).__name__})"
        if err in _LOCAL_AUTH_ERRS:
            raise TuyaAuthError(msg)
        raise TuyaError(msg)


class CloudClient:
    """Tuya developer-cloud access for the cloud-only schedule property."""

    def __init__(self, region: str, client_id: str, client_secret: str) -> None:
        self._region = region
        self._client_id = client_id
        self._client_secret = client_secret
        self._cloud: Any = None

    def connect(self) -> None:
        """Fetch a token if needed. Called from the executor."""
        if getattr(self._cloud, "token", None):
            return
        try:
            cloud = tinytuya.Cloud(
                apiRegion=self._region, apiKey=self._client_id, apiSecret=self._client_secret
            )
        except OSError as err:
            raise TuyaError("Tuya Cloud token request failed") from err
        # tinytuya.Cloud does not raise on bad credentials; token stays None.
        if not getattr(cloud, "token", None):
            err = getattr(cloud, "error", None)
            raise TuyaAuthError(f"cloud auth failed: {str(err)[:160]}")
        self._cloud = cloud

    def _request(self, path: str, what: str, **kwargs: Any) -> dict[str, Any]:
        self.connect()
        try:
            response = self._cloud.cloudrequest(path, **kwargs)
            self._check(response, what)
        except TuyaAuthError:
            self._cloud = None
            raise
        except OSError as err:
            raise TuyaError(f"{what} failed: Tuya Cloud connection error") from err
        return response

    def get_property(self, device_id: str, code: str) -> Any:
        """Read one thing-model shadow property (e.g. skdl_filter)."""
        for prop in self.get_all_properties(device_id) or []:
            if prop.get("code") == code:
                return prop.get("value")
        return None

    def get_model(self, device_id: str) -> Any:
        """Return the device's Tuya thing model (official DP names/types/enums)."""
        resp = self._request(f"/v2.0/cloud/thing/{device_id}/model", "read thing model")
        return resp.get("result")

    def get_all_properties(self, device_id: str) -> Any:
        """Return all shadow properties (raw, for diagnostics)."""
        resp = self._request(
            f"/v2.0/cloud/thing/{device_id}/shadow/properties", "read properties"
        )
        return (resp.get("result") or {}).get("properties")

    def set_property(self, device_id: str, code: str, value: Any) -> None:
        """Write one shadow property via the property-issue API."""
        self._request(
            f"/v2.0/cloud/thing/{device_id}/shadow/properties/issue",
            f"write {code}",
            post={"properties": json.dumps({code: value})},
        )

    @staticmethod
    def _check(resp: Any, what: str) -> None:
        if isinstance(resp, dict) and resp.get("success"):
            return
        if isinstance(resp, dict):
            code = resp.get("code")
            msg = f"{what} failed: code={code} msg={str(resp.get('msg'))[:120]}"
        else:
            code = None
            msg = f"{what} failed: unexpected response ({type(resp).__name__})"
        if code in _CLOUD_AUTH_CODES:
            raise TuyaAuthError(msg)
        raise TuyaError(msg)
