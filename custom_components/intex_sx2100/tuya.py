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

    def _device(self) -> Any:
        dev = tinytuya.Device(self._device_id, self._host, self._local_key)
        dev.set_version(PROTOCOL_VERSION)
        dev.set_socketPersistent(False)
        dev.set_socketTimeout(5)
        return dev

    def status(self) -> dict[str, Any]:
        """Return the DP dict, e.g. {"104": False, "125": "working", ...}."""
        data = self._device().status()
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
        # Constructing tinytuya.Cloud performs a blocking token fetch — always
        # build this inside an executor job.
        self._cloud = tinytuya.Cloud(
            apiRegion=region, apiKey=client_id, apiSecret=client_secret
        )
        # tinytuya.Cloud does not raise on bad credentials; token stays None.
        if getattr(self._cloud, "token", None) is None:
            err = getattr(self._cloud, "error", None)
            raise TuyaAuthError(f"cloud auth failed: {str(err)[:160]}")

    def get_property(self, device_id: str, code: str) -> Any:
        """Read one thing-model shadow property (e.g. skdl_filter)."""
        resp = self._cloud.cloudrequest(
            f"/v2.0/cloud/thing/{device_id}/shadow/properties"
        )
        self._check(resp, "read properties")
        props = (resp.get("result") or {}).get("properties", []) or []
        for prop in props:
            if prop.get("code") == code:
                return prop.get("value")
        return None

    def set_property(self, device_id: str, code: str, value: Any) -> None:
        """Write one shadow property via the property-issue API."""
        resp = self._cloud.cloudrequest(
            f"/v2.0/cloud/thing/{device_id}/shadow/properties/issue",
            post={"properties": json.dumps({code: value})},
        )
        self._check(resp, f"write {code}")

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
