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

# Datapoints (tinytuya returns DP keys as strings)
DP_PUMP = "104"  # pump / filtration on-off (bool)
DP_UNKNOWN_106 = "106"  # unknown bool
DP_UNKNOWN_110 = "110"  # unknown numeric
DP_TIMER = "114"  # timer / remaining / status numeric
DP_UNKNOWN_119 = "119"  # unknown bool
DP_STATE = "125"  # pump state: working / FP_mode / sleep
DP_ALARM = "127"  # alarm state: normal / E93 / ...

# Cloud-only schedule property (the pump's internal timer program)
SCHEDULE_CODE = "skdl_filter"

CLOUD_REGIONS = ["eu", "us", "cn", "in"]
DEFAULT_CLOUD_REGION = "eu"

MANUFACTURER = "Intex"
MODEL = "SX2100 (AGP SAND FILTER PUMP R1)"
DEVICE_NAME = "Intex Pool"

SERVICE_SET_SCHEDULE_SLOT = "set_schedule_slot"
SERVICE_CLEAR_SCHEDULE_SLOT = "clear_schedule_slot"
