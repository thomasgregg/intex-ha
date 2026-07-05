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
| `switch.intex_pool_slot_N` | `skdl_filter` (cloud, optional) | Enable/disable slot N (1-7) |
| `time.intex_pool_slot_N_start` | `skdl_filter` (cloud, optional) | Start time of slot N |
| `number.intex_pool_slot_N_hours` | `skdl_filter` (cloud, optional) | Run time of slot N in hours (1-48) |
| `text.intex_pool_slot_N_days` | `skdl_filter` (cloud, optional) | Repeat days: `daily`, `once` (FP) or `mon,wed,fri` |
| `button.intex_pool_start_fp` | `skdl_filter` (cloud, optional) | Start a one-time FP run (~2 min from now) |
| `number.intex_pool_start_fp_hours` | — | Duration for the Start FP button (1-48 h, default 24) |

**Start FP** writes a dated one-time entry into the first free slot,
starting about two minutes after the press, for "FP hours" hours — the
pump filters continuously, then returns to the normal program (like the
app's FP mode: shock treatment, cloudy water, heat waves). If all 7 slots
are occupied the press fails with a message; clear a slot first. The FP
entry stays in the slot afterwards (disabled) until reused or cleared,
matching the app's behavior.

The slot editors are **configuration entities** — they appear in the
*Configuration* section of the device page, keeping *Controls* to just the
pump switch. Slot entities for slots 4-7 are disabled by default unless the
slot is in use — enable them under *Settings → Devices & Services →
Entities* if needed. (Installs older than 0.3.0 keep their original
`*_schedule_N*` entity IDs.)

### Repeating vs FP-mode slots

The Intex app writes two kinds of entries into the same 7 slots, and each
slot switch exposes which one it is via its `mode` attribute
(live-verified against the real pump's blob):

- `repeating` — a timer with a week mask (`days` 255 = every day, else a
  weekday bitmask).
- `fp_one_time` — the app's **FP mode**: a dated one-off long filtration
  run of up to 48 h (`days` 0, month/date set); the pump reports `FP_mode`
  while it runs and returns to the normal cycle afterwards.

The slot switch mirrors the app's enable toggle (the `on` byte) for both
kinds — it never changes the slot's mode or timing.

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

## Polling

The pump is polled **locally** every 15 s (no cloud involved, no API quota).
The cloud schedule blob is polled every **15 minutes** by default — schedules
rarely change outside HA, and this keeps well within Tuya's free-tier API
limits. After you edit a slot there is a single extra read ~5 s later to
confirm the write. Both intervals are configurable under
*Settings → Devices & Services → Intex SX2100 Pool Pump → Configure*.

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

## Dashboard card

Device pages are utilitarian; for a nicer pool card, paste this into a
manual card (adjust entity IDs if your install predates 0.3.0):

```yaml
type: entities
title: Pool Pump
entities:
  - entity: switch.intex_pool_pump
    name: Pump
  - entity: sensor.intex_pool_status
    name: Status
  - entity: sensor.intex_pool_alarm
    name: Alarm
  - type: divider
  - entity: switch.intex_pool_slot_1
    name: Schedule 1
    secondary_info: attribute
    attribute: summary
  - entity: time.intex_pool_slot_1_start
    name: "  Start"
  - entity: number.intex_pool_slot_1_hours
    name: "  Hours"
  - type: divider
  - entity: switch.intex_pool_slot_2
    name: Schedule 2
    secondary_info: attribute
    attribute: summary
  - entity: time.intex_pool_slot_2_start
    name: "  Start"
  - entity: number.intex_pool_slot_2_hours
    name: "  Hours"
```

## Protocol notes (verified against the real pump)

```text
protocol: 3.5 (3.3 -> Err 904, 3.4 -> Err 914)
DP 104: pump on/off        (set true -> state FP_mode, false -> working)
DP 125: state              working / FP_mode / sleep
DP 127: alarm              normal / E93
DP 114: timer/remaining    numeric
```

Week byte of a schedule slot (live-verified Mon-only -> 192, Wed-only -> 144):

```text
bit 7 (128) = weekly-repeat flag
bit 6 (64)  = Mon    bit 5 (32) = Tue    bit 4 (16) = Wed    bit 3 (8) = Thu
bit 2 (4)   = Fri    bit 1 (2)  = Sat    bit 0 (1)  = Sun
255 = every day · 0 = dated one-time FP entry
```

Note: creating a *new* FP entry (setting days to `once`) reuses whatever
month/date bytes the slot already holds — set the date via the Intex app,
or use the `set_schedule_slot` service.

Each poll and command uses a fresh, non-persistent socket — persistent
sockets were observed to serve stale DP values and swallow commands.

## Credits

The `skdl_filter` 7×8-byte blob format follows the reverse-engineering
documented in [Hovborg/intex-pool](https://github.com/Hovborg/intex-pool)
(MIT). This integration is an independent, minimal, pump-only implementation.

## License

MIT
