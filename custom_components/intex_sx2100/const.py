"""Constants for the Intex SX2100 integration."""
from __future__ import annotations

DOMAIN = "intex_sx2100"

# Config entry keys
CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_CLOUD_REGION = "cloud_region"
CONF_CLOUD_CLIENT_ID = "cloud_client_id"
CONF_CLOUD_CLIENT_SECRET = "cloud_client_secret"

# Options
OPT_LOCAL_INTERVAL = "local_interval"
OPT_CLOUD_INTERVAL = "cloud_interval"
DEFAULT_LOCAL_INTERVAL = 15  # seconds
DEFAULT_CLOUD_INTERVAL = 900  # seconds — schedules rarely change; spare the cloud API quota

# The only protocol version this pump answers on (3.3 -> Err 904, 3.4 -> Err 914).
PROTOCOL_VERSION = 3.5

# Datapoints (tinytuya returns DP keys as strings).
# Official Tuya thing-model names, dumped from the real pump 2026-07-05.
DP_PUMP = "104"  # power_switch (rw bool)
DP_FILTER_SWITCH = "106"  # filter_switch (rw bool) — effect untested!
DP_WORKING_TIME = "110"  # working_time (ro value, 0-250 hours)
DP_ERROR_BITMAP = "114"  # error_code (ro bitmap, see ERROR_BIT_LABELS)
DP_MESH = "119"  # mesh_indicator (ro bool)
DP_STATE = "125"  # working_indicator: working / FP_mode / sleep / boost
DP_ALARM = "127"  # warntype_indicator: normal / E93 / DIRTY / unnormal

# error_code bitmap: bit index -> thing-model label. Label 1xx corresponds to
# the app's Exx display (observed live: bit 5 set (32) while DP 127 showed
# E93; label at index 5 is '193').
ERROR_BIT_LABELS = [
    "181", "180", "190", "191", "192", "193",
    "194", "195", "196", "199", "200", "197",
]


# Codes that are NOT faults. E93 is Intex's standby / power-saving state; it
# appears both in warntype_indicator (127) and as a bit in error_code (114)
# while the pump idles between scheduled runs.
NON_FAULT_CODES = frozenset({"E93"})


def decode_error_bits(value: int) -> list[str]:
    """Decode the error_code bitmap into app-style codes, e.g. [1] -> ['E80'].

    Faithful decode of every set bit, including the non-fault E93 standby bit.
    """
    return [
        f"E{int(label) - 100}"
        for i, label in enumerate(ERROR_BIT_LABELS)
        if value >> i & 1
    ]


def fault_codes(value: int) -> list[str]:
    """Like ``decode_error_bits`` but excludes non-fault codes (E93 standby)."""
    return [c for c in decode_error_bits(value) if c not in NON_FAULT_CODES]

# Cloud-only schedule property (the pump's internal timer program)
SCHEDULE_CODE = "skdl_filter"

CLOUD_REGIONS = ["eu", "us", "cn", "in"]
DEFAULT_CLOUD_REGION = "eu"

MANUFACTURER = "Intex"
MODEL = "SX2100 (AGP SAND FILTER PUMP R1)"
DEVICE_NAME = "Intex Pool"

SERVICE_SET_SCHEDULE_SLOT = "set_schedule_slot"
SERVICE_CLEAR_SCHEDULE_SLOT = "clear_schedule_slot"
