# Intex SX2100 Pool Pump for Home Assistant

Minimal Home Assistant custom integration for the **Intex SX2100 WiFi sand
filter pump** (Tuya device `AGP SAND FILTER PUMP R1`, category `rs`, product
`ff6aa9iqer5r7wtg`).

Local control via [tinytuya](https://github.com/jasonacox/tinytuya) on
**Tuya protocol 3.5** (this pump rejects 3.3 with Err 904 and 3.4 with
Err 914). No saltwater system, no spa, no water-quality sensor, no generic
Tuya abstraction — just this pump.

## Entities

| Entity | Source | Meaning |
|---|---|---|
| `switch.intex_pool_pump` | DP 104 (local) | Filtration on/off |
| `sensor.intex_pool_status` | DP 125 (local) | `working` / `FP_mode` / `sleep` |
| `sensor.intex_pool_alarm` | DP 127 (local) | `normal` / `E93` / … |
| `sensor.intex_pool_timer_or_remaining` | DP 114 (local) | Timer / remaining numeric |
| `sensor.intex_pool_schedule` | `skdl_filter` (cloud, optional) | Active timer slots (details in attributes) |
| `switch.intex_pool_schedule_N` | `skdl_filter` (cloud, optional) | Enable/disable slot N (1-7) |
| `time.intex_pool_schedule_N_start` | `skdl_filter` (cloud, optional) | Start time of slot N |
| `number.intex_pool_schedule_N_duration` | `skdl_filter` (cloud, optional) | Run time of slot N in hours |

Slot entities for slots 4-7 are disabled by default unless the slot is in
use — enable them under *Settings → Devices & Services → Entities* if needed.

Other observed DPs (106 bool, 110 numeric, 119 bool) are unknown and not
exposed yet.

## Installation

**HACS:** add `https://github.com/thomasgregg/intex-ha` as a custom
repository (type *Integration*), install, restart Home Assistant.

**Manual:** copy `custom_components/intex_sx2100` into your `config/custom_components/`
directory and restart.

Then: *Settings → Devices & Services → Add Integration → Intex SX2100 Pool Pump*.

## Configuration

Required (local control):

- **IP address** — e.g. `192.168.178.146` (give the pump a static DHCP lease)
- **Device ID** and **Local key** — extract with `python -m tinytuya wizard`

Optional (schedule support): a Tuya IoT platform **client ID** and **client
secret** from [iot.tuya.com](https://iot.tuya.com) (cloud project linked to
the Intex/Smart Life app account, data center = your region, e.g. `eu`).
Without them the integration is fully local and simply has no schedule
entities. The pump's internal timer program (`skdl_filter`) exists only in
the Tuya cloud — it is never reported on the LAN.

## Schedule services

The `skdl_filter` program has 7 slots of 8 bytes
(`month date hour minute worktime week control pad`), base64-encoded.
The integration exposes two services:

```yaml
# Run daily at 06:00 for 8 hours, slot 1
service: intex_sx2100.set_schedule_slot
data:
  slot: 1
  enabled: true
  hour: 6
  minute: 0
  duration: 8
  days: 255   # 255 = every day
```

```yaml
service: intex_sx2100.clear_schedule_slot
data:
  slot: 1
```

`sensor.intex_pool_schedule` shows the number of active slots; its
attributes contain the decoded slots, human-readable summaries and the raw
base64 blob.

## Protocol notes (verified against the real pump)

```text
protocol: 3.5 (3.3 -> Err 904, 3.4 -> Err 914)
DP 104: pump on/off        (set true -> state FP_mode, false -> working)
DP 125: state              working / FP_mode / sleep
DP 127: alarm              normal / E93
DP 114: timer/remaining    numeric
```

Each poll and command uses a fresh, non-persistent socket — persistent
sockets were observed to serve stale DP values and swallow commands.

## Credits

The `skdl_filter` 7×8-byte blob format follows the reverse-engineering
documented in [Hovborg/intex-pool](https://github.com/Hovborg/intex-pool)
(MIT). This integration is an independent, minimal, pump-only implementation.

## License

MIT
