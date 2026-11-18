# ILSE S2 Gateway

Exposes Home Assistant devices as **S2 resource managers** (EN 50491-12-2) to an
external customer energy manager (CEM). Any device Home Assistant can read, through
any integration, gets a standard S2 description of its flexibility.

**Version 0.1 is read-only (shadow mode).** The gateway describes the devices,
reports state and power, and receives instructions from the CEM. It acknowledges
each instruction, reports it back as `REJECTED` and logs what it would have done.
Nothing is ever written to Home Assistant.

## How it works

- One resource manager per device, each with its own WebSocket connection to the
  CEM. In S2 over WebSocket the resource manager is the client.
- Device ids are stable (derived from the site name and device name), so the CEM
  recognises a device after a restart.
- Power is in W. Positive is consumption (charging), negative is production
  (discharging).

| Device type | S2 control type | Described as |
| --- | --- | --- |
| `battery` | FRBC (fill rate based) | fill level = state of charge in %, operation modes charge, idle, discharge |
| `ev` | FRBC (fill rate based) | fill level = the car's state of charge; idle always, charge (min to max power) only while plugged in; optional target as fill level target profile |
| `switch` | OMBC (operation mode based) | operation modes off and on at a fixed power |
| `pv` | not controllable (for now) | measurements only; curtailment through PEBC follows |

Both also offer "not controllable", for a CEM that only wants measurements.

## Options

| Option | Meaning |
| --- | --- |
| `site_name` | Name of this installation, used in the device names and ids (default: host name) |
| `cem_url` | WebSocket URL of the CEM; `{rm_id}` is replaced by the device id |
| `self_test_cem` | Start a minimal test CEM inside the add-on on the port of `cem_url` |
| `self_test_every_min` | Repeat the self-test instruction every N minutes (0 = once) |
| `interval_s` | How often status and power are sent |
| `devices` | List of devices (see below) |

Per device:

| Field | For | Meaning |
| --- | --- | --- |
| `name` | all | Device name |
| `type` | all | `battery`, `ev`, `switch` or `pv` |
| `label` | all | Optional model or description shown on the web page |
| `icon` | all | Optional illustration: battery, inverter, charger, car, boiler, switch, pv |
| `power_entity` | all | Power sensor (W or kW) |
| `power_factor` | all | Multiply the sensor by this to get positive = consumption (often `-1` for batteries) |
| `soc_entity` | battery | State of charge sensor (%) |
| `capacity_kwh`, `max_charge_w`, `max_discharge_w` | battery | Size and power limits |
| `plugged_entity` | ev | Entity that tells whether the car is plugged in |
| `plugged_state` | ev | State of `plugged_entity` that means plugged in (default `on`) |
| `min_charge_w`, `max_charge_w`, `capacity_kwh` | ev | Charging power range and battery size |
| `target_soc`, `departure` | ev | Optional target: at least `target_soc` % at `departure` (HH:MM, local time) |
| `state_entity` | switch | Optional on/off entity |
| `power_w` | switch | Power when on |

## Web page

Open **S2 Gateway** in the Home Assistant sidebar. Per device you see who is in control:

| Status | Meaning |
| --- | --- |
| ILSE in control | no external energy manager connected |
| Energy manager connected, watching only | connected, but no control type that allows steering |
| External energy manager may steer | a control type was selected, no instruction in the last 15 minutes |
| Taken over by external energy manager | instructions received in the last 15 minutes (in shadow mode: logged, not executed) |

Plus live state of charge and power, the last instruction and a timeline of
connections, control type changes and instructions.

## Self-test

With `self_test_cem: true` and `cem_url: ws://127.0.0.1:8003/ws/{rm_id}`, the add-on
runs a minimal test CEM next to the gateway. In the log you see the handshake, the
selected control type per device, the descriptions, state of charge, measurements,
one test instruction per device and the `REJECTED` answer. Events are also written
to `/data/s2_events.jsonl` inside the add-on.

To connect to a real CEM, set `self_test_cem: false` and point `cem_url` to it.
