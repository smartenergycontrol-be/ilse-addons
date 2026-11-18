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
| `switch` | OMBC (operation mode based) | operation modes off and on at a fixed power |

Both also offer "not controllable", for a CEM that only wants measurements.

## Options

| Option | Meaning |
| --- | --- |
| `site_name` | Name of this installation, used in the device names and ids (default: host name) |
| `cem_url` | WebSocket URL of the CEM; `{rm_id}` is replaced by the device id |
| `self_test_cem` | Start a minimal test CEM inside the add-on on the port of `cem_url` |
| `interval_s` | How often status and power are sent |
| `devices` | List of devices (see below) |

Per device:

| Field | For | Meaning |
| --- | --- | --- |
| `name` | all | Device name |
| `type` | all | `battery` or `switch` |
| `power_entity` | all | Power sensor (W or kW) |
| `power_factor` | all | Multiply the sensor by this to get positive = consumption (often `-1` for batteries) |
| `soc_entity` | battery | State of charge sensor (%) |
| `capacity_kwh`, `max_charge_w`, `max_discharge_w` | battery | Size and power limits |
| `state_entity` | switch | Optional on/off entity |
| `power_w` | switch | Power when on |

## Self-test

With `self_test_cem: true` and `cem_url: ws://127.0.0.1:8003/ws/{rm_id}`, the add-on
runs a minimal test CEM next to the gateway. In the log you see the handshake, the
selected control type per device, the descriptions, state of charge, measurements,
one test instruction per device and the `REJECTED` answer. Events are also written
to `/data/s2_events.jsonl` inside the add-on.

To connect to a real CEM, set `self_test_cem: false` and point `cem_url` to it.
